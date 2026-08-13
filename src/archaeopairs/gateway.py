"""模型网关（对齐《技术方案 V0.1》§9.1 / §5.8 / §5.9.3 / §3.7）。

职责：调用录制/回放、限流、熔断（60s 恢复）、指数退避重试（4xx 不重试）、
单图成本帽（超限→PENDING_REVIEW）。trace_id 贯穿。统计有界。
"""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Callable

from .errors import ArchaeoPairsError, E1000ServiceUnavailableError

DEFAULT_TIMEOUT = {"vlm": 30.0, "sam": 20.0, "ocr": 10.0}


class CostCapExceeded(ArchaeoPairsError):
    """单图成本帽超限（§5.9.3），转 PENDING_REVIEW。"""

    code = "COST"


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, ArchaeoPairsError):
        return getattr(exc, "retryable", False)
    return False


class Gateway:
    """模型网关：录制/回放/限流/熔断/成本帽。"""

    def __init__(self, *, per_figure_cap_cny: float = 2.0, circuit_threshold: int = 3,
                 circuit_recovery_s: float = 60.0, max_retries: int = 3,
                 replay: dict | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cap = per_figure_cap_cny
        self.circuit_threshold = circuit_threshold
        self.circuit_recovery_s = circuit_recovery_s
        self.max_retries = max_retries
        self.sleep = sleep
        self._open_until: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self.calls: deque = deque(maxlen=10000)
        self.cost_by_figure: dict[str, float] = {}
        self._replay = replay or {}

    def _circuit_open(self, service: str) -> bool:
        until = self._open_until.get(service, 0.0)
        if until and time.time() < until:
            return True
        if until:  # 恢复窗口到，半开重置
            self._open_until[service] = 0.0
            self._failures[service] = 0
        return False

    def call(self, service: str, fn: Callable[..., Any], *, figure_id: str,
             trace_id: str, cost: float = 0.0, operation: str = "call",
             iteration: int = 0, **kwargs: Any) -> Any:
        key = f"{service}:{operation}:{figure_id}:{iteration}"
        if key in self._replay:
            self.calls.append({"key": key, "mode": "replay", "request": kwargs,
                               "response": self._replay[key]})
            return self._replay[key]
        if self._circuit_open(service):
            raise E1000ServiceUnavailableError(f"{service} circuit open")
        if self.cost_by_figure.get(figure_id, 0.0) >= self.cap:
            raise CostCapExceeded(figure_id)

        attempt = 0
        while True:
            try:
                result = fn(**kwargs, trace_id=trace_id, figure_id=figure_id,
                            timeout=DEFAULT_TIMEOUT.get(service, 30.0))
            except Exception as exc:  # noqa: BLE001 - 网关统一重试判定
                if not _retryable(exc) or attempt >= self.max_retries - 1:
                    self._failures[service] = self._failures.get(service, 0) + 1
                    if self._failures[service] >= self.circuit_threshold:
                        self._open_until[service] = time.time() + self.circuit_recovery_s
                    raise
                self.sleep(min(0.5 * (2 ** attempt), 5.0))
                attempt += 1
                continue
            break
        self._failures[service] = 0
        self.cost_by_figure[figure_id] = self.cost_by_figure.get(figure_id, 0.0) + cost
        self.calls.append({"key": key, "mode": "live", "ts": time.time(),
                           "request": kwargs, "response": result})
        return result

    def reset_figure(self, figure_id: str) -> None:
        """单图完成释放成本计数，防无界累积。"""
        self.cost_by_figure.pop(figure_id, None)

    def recording(self) -> str:
        """导出录制（JSON 行），供回放复算。"""
        return json.dumps(list(self.calls), ensure_ascii=False)

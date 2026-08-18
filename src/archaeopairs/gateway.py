"""模型网关（对齐《技术方案 V0.4》部署拓扑（§9.1）/ 服务级降级（§3.7）/ 能力接口契约（§5.1.4））。

职责：调用录制/回放、指数退避重试（4xx 不重试）、按 Worker 配额限流（防 GPU 打爆）、
可配超时、trace_id 贯穿、统计有界。
成本帽与熔断已按 V0.4 范围收敛移除（§9.2 资源估算与 §3.7 服务级降级覆盖可用性）。
"""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Callable

from .errors import ArchaeoPairsError

DEFAULT_TIMEOUT = {"vlm": 30.0, "sam": 20.0, "ocr": 10.0}


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, ArchaeoPairsError):
        return getattr(exc, "retryable", False)
    return False


class Gateway:
    """模型网关：录制/回放/重试/限流（Worker 配额）。"""

    def __init__(self, *, max_retries: int = 3, replay: dict | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 timeouts: dict | None = None, rate_limits: dict | None = None) -> None:
        self.max_retries = max_retries
        self.sleep = sleep
        self.calls: deque = deque(maxlen=10000)
        self._replay = replay or {}
        self.timeouts: dict[str, float] = {**DEFAULT_TIMEOUT, **(timeouts or {})}
        self.rate_limits: dict[str, float] = rate_limits or {}  # {service: QPS}，空=不限
        self._window: dict[str, tuple[float, int]] = {}  # service -> (窗口起点, 窗口内调用数)

    def _throttle(self, service: str) -> None:
        """按 Worker 配额限流（固定 1s 窗口）：每秒至多 QPS 次，超限等待至下一窗口。"""
        qps = self.rate_limits.get(service, 0.0)
        if qps <= 0:
            return
        now = time.time()
        wstart, count = self._window.get(service, (0.0, 0))
        if now - wstart >= 1.0:
            self._window[service] = (now, 1)
            return
        if count < qps:
            self._window[service] = (wstart, count + 1)
            return
        wait = 1.0 - (now - wstart)
        if wait > 0:
            self.sleep(wait)
        self._window[service] = (now + 1.0, 1)

    def call(self, service: str, fn: Callable[..., Any], *, figure_id: str,
             trace_id: str, operation: str = "call",
             iteration: int = 0, **kwargs: Any) -> Any:
        key = f"{service}:{operation}:{figure_id}:{iteration}"
        if key in self._replay:
            self.calls.append({"key": key, "mode": "replay", "request": kwargs,
                               "response": self._replay[key]})
            return self._replay[key]
        self._throttle(service)
        attempt = 0
        while True:
            try:
                result = fn(**kwargs, trace_id=trace_id, figure_id=figure_id,
                            timeout=self.timeouts.get(service, 30.0))
            except Exception as exc:  # noqa: BLE001 - 网关统一重试判定
                if not _retryable(exc) or attempt >= self.max_retries - 1:
                    raise
                self.sleep(min(0.5 * (2 ** attempt), 5.0))
                attempt += 1
                continue
            break
        self.calls.append({"key": key, "mode": "live", "ts": time.time(),
                           "request": kwargs, "response": result})
        return result

    def recording(self) -> str:
        """导出录制（JSON 行），供回放复算。"""
        return json.dumps(list(self.calls), ensure_ascii=False)

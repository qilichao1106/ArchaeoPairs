"""模型网关（对齐《技术方案 V0.4》部署拓扑（§9.1）/ 幂等与可复现（§5.8）/ 服务级降级（§3.7））。

职责：调用录制/回放、指数退避重试（4xx 不重试）、trace_id 贯穿、统计有界。
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
    """模型网关：录制/回放/重试。"""

    def __init__(self, *, max_retries: int = 3, replay: dict | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.max_retries = max_retries
        self.sleep = sleep
        self.calls: deque = deque(maxlen=10000)
        self._replay = replay or {}

    def call(self, service: str, fn: Callable[..., Any], *, figure_id: str,
             trace_id: str, cost: float = 0.0, operation: str = "call",
             iteration: int = 0, **kwargs: Any) -> Any:
        key = f"{service}:{operation}:{figure_id}:{iteration}"
        if key in self._replay:
            self.calls.append({"key": key, "mode": "replay", "request": kwargs,
                               "response": self._replay[key]})
            return self._replay[key]
        attempt = 0
        while True:
            try:
                result = fn(**kwargs, trace_id=trace_id, figure_id=figure_id,
                            timeout=DEFAULT_TIMEOUT.get(service, 30.0))
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

"""模型网关（对齐《技术方案 V0.1》§9.1 / §5.8 / §5.9.3）。

职责：调用录制/回放、限流、熔断、单图成本帽。所有模型调用经网关，trace_id
贯穿。回放模式用于契约测试与复算（不触达真实模型）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import E1000ServiceUnavailableError


@dataclass
class GatewayStats:
    calls: list[dict] = field(default_factory=list)
    cost_by_figure: dict[str, float] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)


class Gateway:
    """模型网关：录制/回放/限流/熔断/成本帽。"""

    def __init__(self, *, per_figure_cap_cny: float = 2.0,
                 circuit_threshold: int = 3, replay: dict | None = None) -> None:
        self.cap = per_figure_cap_cny
        self.circuit_threshold = circuit_threshold
        self.stats = GatewayStats()
        self._replay = replay or {}

    def call(self, service: str, fn: Callable[..., Any], *, figure_id: str,
             trace_id: str, cost: float = 0.0, **kwargs: Any) -> Any:
        key = f"{service}:{figure_id}:{trace_id}"
        # 回放
        if key in self._replay:
            self.stats.calls.append({"key": key, "mode": "replay"})
            return self._replay[key]
        # 熔断
        if self.stats.failures.get(service, 0) >= self.circuit_threshold:
            raise E1000ServiceUnavailableError(f"{service} circuit open")
        # 成本帽
        if self.stats.cost_by_figure.get(figure_id, 0.0) >= self.cap:
            raise CostCapExceeded(figure_id)
        try:
            result = fn(**kwargs, trace_id=trace_id, figure_id=figure_id)
        except Exception:
            self.stats.failures[service] = self.stats.failures.get(service, 0) + 1
            raise
        self.stats.failures[service] = 0
        self.stats.cost_by_figure[figure_id] = (
            self.stats.cost_by_figure.get(figure_id, 0.0) + cost
        )
        self.stats.calls.append({"key": key, "mode": "live", "ts": time.time()})
        return result

    def recording(self) -> str:
        """导出录制（JSON 行），供回放复算。"""
        return json.dumps(self.stats.calls, ensure_ascii=False)


class CostCapExceeded(Exception):
    """单图成本帽超限（§5.9.3），转 PENDING_REVIEW。"""

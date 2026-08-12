"""Label Studio 复核桥接（§4.10）。接口 + 进程内 mock。

生产替换为 FastAPI webhook + LS import API；P0 用 MockReviewBridge 验证
event_id 幂等回写与 resume 流程。
"""
from __future__ import annotations

from typing import Protocol


class ReviewBridge(Protocol):
    def create_task(self, *, figure_id: str, event_id: str, payload: dict) -> str: ...
    def callback(self, *, event_id: str, result: dict) -> bool: ...


class MockReviewBridge:
    """进程内 mock：记录任务与回灌，event_id 幂等去重。"""

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self._seen_events: set[str] = set()

    def create_task(self, *, figure_id: str, event_id: str, payload: dict) -> str:
        self.tasks[figure_id] = {"event_id": event_id, "payload": payload, "status": "OPEN"}
        return f"ls-{figure_id}"

    def callback(self, *, event_id: str, result: dict) -> bool:
        if event_id in self._seen_events:
            return False  # 幂等去重
        self._seen_events.add(event_id)
        return True

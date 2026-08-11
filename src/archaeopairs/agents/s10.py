"""S10 调度复核桥接器（§4.10）。Node: 输出/人工复核桥接（interrupt）。"""
from __future__ import annotations

from langgraph.types import interrupt

from . import Services


def run(state: dict, svc: Services) -> dict:
    pending = (state.get("case_type") == "seq_missing") or (
        bool(state.get("defect_history")) and state.get("defect_history", [0])[-1] > 0
        and state.get("iteration", 0) >= svc.thresholds.max_iteration
    )
    if pending:
        if svc.flags.require_human:
            # 挂起等待 Label Studio 复核回灌（Command(resume=...) 恢复）
            interrupt({"figure_id": state["figure_id"], "reason": "PENDING_REVIEW"})
        return {"status": "PENDING_REVIEW", "review_events": [{"type": "pending"}]}
    return {"status": "OUTPUT", "review_events": [{"type": "output"}]}

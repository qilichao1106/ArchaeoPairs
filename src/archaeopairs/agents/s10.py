"""S10 调度复核桥接器（§4.10）。Node: 输出/人工复核桥接（interrupt+幂等回写）。

整改：处理 E001–E007/seq_missing/降级/迭代上限；event_id 由
(figure_id, 报警集合, 排除原因) 确定性生成，重跑/续跑不再产生重复复核任务；
经 LS 桥接创建复核任务（event_id 幂等）；require_human 时 interrupt 挂起等待 resume。
"""
from __future__ import annotations

import hashlib

from langgraph.types import interrupt

from . import Services


def event_id_of(state: dict) -> str:
    alarms = ",".join(sorted(state.get("alarms") or []))
    reason = state.get("exclude_reason") or ""
    key = f"{state['figure_id']}|{alarms}|{reason}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"{state['figure_id']}:{digest}"


def _is_pending(state: dict, max_iteration: int) -> bool:
    if state.get("alarms") or state.get("no_improve"):
        return True
    if state.get("case_type") == "seq_missing" and not state.get("degraded"):
        return True
    if state.get("degraded"):
        fused = state.get("fused") or {}
        if not fused.get("seq_to_artifacts"):
            return True
    hist = state.get("defect_history") or [0]
    return hist[-1] > 0 and state.get("iteration", 0) >= max_iteration


def run(state: dict, svc: Services) -> dict:
    if _is_pending(state, svc.thresholds.max_iteration):
        event_id = event_id_of(state)
        if svc.review_bridge is not None:
            svc.review_bridge.create_task(
                figure_id=state["figure_id"], event_id=event_id,
                payload={"alarms": state.get("alarms", []),
                         "case_type": state.get("case_type")},
            )
        if svc.flags.require_human:
            # 挂起等待 Label Studio 复核回灌（Command(resume=...) 恢复）
            interrupt({"figure_id": state["figure_id"], "reason": "PENDING_REVIEW",
                       "event_id": event_id})
        return {"status": "PENDING_REVIEW",
                "review_events": [{"type": "pending", "event_id": event_id}]}
    return {"status": "OUTPUT", "review_events": [{"type": "output"}]}

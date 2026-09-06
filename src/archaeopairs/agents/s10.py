"""S10 调度复核桥接器（§4.10）。Node: 输出/人工复核桥接（interrupt+幂等回写）。

两级分流（V0.5.4）：合格/无缺陷 → 输出 Pair 入库；不合格/存疑（S9 质检
reject、E001–E007 报警、seq_missing、降级无映射证据、S6/S8 判定 PENDING_REVIEW）
→ 携带质检报告转 Label Studio 复核。event_id 由 (figure_id, 报警集合, 排除原因)
确定性生成，重跑/续跑不再产生重复复核任务；经 LS 桥接创建复核任务（event_id
幂等）；require_human 时 interrupt 挂起等待 resume。
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


def _is_pending(state: dict) -> bool:
    """两级分流判定（§4.9.2/§4.10）：不合格/存疑 → 复核；合格 → 输出入库。"""
    if state.get("status") == "PENDING_REVIEW":
        return True
    if state.get("alarms"):
        return True
    # S9 质检结论（V0.5.4 纯质检门）：reject / 有缺陷 → 复核
    qc = state.get("qc_report") or {}
    if qc.get("qc_verdict") == "reject" or qc.get("defect_list"):
        return True
    if state.get("case_type") == "seq_missing" and not state.get("degraded"):
        return True
    if state.get("degraded"):
        fused = state.get("fused") or {}
        # 图题兜底器物号（§2.2.5）同样视为可用映射证据
        if (not fused.get("seq_to_artifacts") and not fused.get("caption_artifacts")
                and not state.get("single_artifacts")):
            return True
    return False


def run(state: dict, svc: Services) -> dict:
    if _is_pending(state):
        event_id = event_id_of(state)
        if svc.review_bridge is not None:
            svc.review_bridge.create_task(
                figure_id=state["figure_id"], event_id=event_id,
                payload={"alarms": state.get("alarms", []),
                         "case_type": state.get("case_type"),
                         "qc_report": state.get("qc_report")},
            )
        if svc.flags.require_human:
            # 挂起等待 Label Studio 复核回灌（Command(resume=...) 恢复）
            interrupt({"figure_id": state["figure_id"], "reason": "PENDING_REVIEW",
                       "event_id": event_id})
        return {"status": "PENDING_REVIEW",
                "review_events": [{"type": "pending", "event_id": event_id}]}
    return {"status": "OUTPUT", "review_events": [{"type": "output"}]}

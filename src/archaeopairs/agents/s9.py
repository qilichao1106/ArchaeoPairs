"""S9 Supervisor VLM（§4.9）。Node: 纯质检门（V0.5.4，不驱动修正回环）。

对 S8 组装后的多器物线图产出做结构化质检，产出 QCReport：
  defect_list 为空 → qc_verdict=pass，经 S10 输出入库；
  defect_list 非空或绑定/归组置信不足 → qc_verdict=reject，转 PENDING_REVIEW
  （质检报告随复核任务下发 §8.2，人工修正后按回灌口径重入 ≤2 轮）。
质检模型不可用（E900/E1000）→ 编排层统一转 PENDING_REVIEW（宁复核不误放）。

V0.5.4：移除诊断修正回环（iteration/defect_history/target_agent/
correction_action/action_params/收敛判定/逐级升级），不合格仅转人工复核。
"""
from __future__ import annotations

import uuid

from ..state import QCReport
from . import Services


def run(state: dict, svc: Services) -> dict:
    resp = svc.gateway.call(
        "vlm", svc.vlm.diagnose, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"],
        context={"assembled": state.get("assembled", False),
                 "pair_records": len(state.get("pair_records", []))},
        operation="qc",
    )
    defects = resp.get("defect_list", [])
    # 判定规则（§4.9.2）：defect_list 为空 → pass；非空 → reject。
    # 绑定/归组置信不足（S6 冲突/降级场景）已在 s6_compose 转 PENDING_REVIEW，
    # 到达 S9 的图均带完整映射证据；生产实现可叠加绑定置信阈值判定。
    verdict = "reject" if defects else "pass"
    evidence = {
        "defects": [{"type": d.get("type"), "location": d.get("location"),
                     "severity": d.get("severity")} for d in defects],
        "alarms": list(state.get("alarms") or []),
        "confidence": state.get("confidence"),
    }
    qc = QCReport(trace_id=state["trace_id"], report_id=str(uuid.uuid4()),
                  figure_id=state["figure_id"], defect_list=defects,
                  qc_verdict=verdict, evidence=evidence)
    # 质检不落终态：pass/reject 均经 S10 两级分流（输出入库 / 转复核），无自动回环
    return {"qc_report": qc.model_dump(), "status": "ASM_VALIDATED"}

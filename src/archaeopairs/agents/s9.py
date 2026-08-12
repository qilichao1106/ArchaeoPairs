"""S9 Supervisor VLM（§4.9）。Node: 结构化诊断+收敛判定+逐级升级。

整改：实现"连续两轮无改善→不收敛"判定；逐级升级（1 原信号/2 +few-shot/3 高档位）；
指导信号（提示点/阈值）写入 action_params 供 S6 消费。
"""
from __future__ import annotations

import uuid

from . import Services
from .alarms import defect_target


def run(state: dict, svc: Services) -> dict:
    resp = svc.gateway.call(
        "vlm", svc.vlm.diagnose, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], context={"assembled": state.get("assembled", False)},
    )
    defects = resp.get("defect_list", [])
    iteration = state.get("iteration", 0)
    history = list(state.get("defect_history", []))
    history.append(len(defects))

    th = svc.thresholds
    # 连续两轮无改善 → 不收敛
    no_improve = len(history) >= 2 and history[-1] >= history[-2]
    converged = len(defects) == 0
    if not converged and not no_improve and svc.flags.s9_loop and iteration < th.max_iteration:
        iteration += 1
    escalation = min(iteration + 1, 3)
    action_params: dict = {}
    if defects:
        action_params = {"points": resp.get("points", [])}
        if escalation >= 2:
            action_params["few_shot"] = True
        if escalation >= 3:
            action_params["model_tier"] = "high"
    diagnostic = {
        "trace_id": state["trace_id"], "report_id": str(uuid.uuid4()),
        "figure_id": state["figure_id"], "defect_list": defects,
        "target_agent": (defect_target(defects[0]["type"]) if defects else None),
        "correction_action": (defects[0].get("correction_action") if defects else None),
        "action_params": action_params, "expected_result": resp.get("expected_result"),
        "iteration": iteration, "escalation_level": escalation,
    }
    return {"diagnostic": diagnostic, "iteration": iteration,
            "defect_history": history, "status": "SEG_DIAGNOSED"}

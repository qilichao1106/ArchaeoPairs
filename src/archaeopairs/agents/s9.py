"""S9 Supervisor VLM（§4.9）。Node: 结构化诊断→DiagnosticReport+迭代/收敛判定。"""
from __future__ import annotations

import uuid

from . import Services


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
    converged = len(defects) == 0
    if not converged and svc.flags.s9_loop and iteration < th.max_iteration:
        iteration += 1
    diagnostic = {
        "trace_id": state["trace_id"], "report_id": str(uuid.uuid4()),
        "figure_id": state["figure_id"], "defect_list": defects,
        "target_agent": (defects[0].get("target_agent") if defects else None),
        "correction_action": (defects[0].get("correction_action") if defects else None),
        "action_params": {}, "expected_result": None, "iteration": iteration,
    }
    return {"diagnostic": diagnostic, "iteration": iteration,
            "defect_history": history, "status": "SEG_DIAGNOSED"}

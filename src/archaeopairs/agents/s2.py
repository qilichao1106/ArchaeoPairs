"""S2 图类判定器（§4.2）。Node: 视觉+XML 图题关键词判 image_type。"""
from __future__ import annotations

from . import Services


def run(state: dict, svc: Services) -> dict:
    resp = svc.gateway.call(
        "vlm", svc.vlm.classify, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], caption=state.get("caption"),
        operation="classify", iteration=state.get("iteration", 0),
        cost=svc.thresholds.model_costs.get("vlm", 0.0),
    )
    return {"image_type": resp["image_type"], "status": "CLASSIFIED"}

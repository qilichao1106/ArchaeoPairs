"""S6 视觉分割器（§4.6）。Node: SAM 掩膜分割（掩膜三件套，禁 bbox）。"""
from __future__ import annotations

from ..errors import HardConstraintError
from . import Services


def run(state: dict, svc: Services) -> dict:
    masks = svc.gateway.call(
        "sam", svc.sam.segment, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], prompts=[],
    )
    for m in masks:  # 硬约束：必须为掩膜，禁 bbox 切割
        if not m.get("mask_rle"):
            raise HardConstraintError("mask 必须为掩膜(RLE)，禁 bbox")
    return {"masks": masks, "status": "SEG_DIAGNOSED"}

"""S6 视觉分割器（§4.6）。Node: SAM 掩膜分割（掩膜三件套，禁 bbox）。

整改：消费 S9 指导信号（提示点/阈值）做针对性二次分割；掩膜残缺触发 E006。
"""
from __future__ import annotations

from ..errors import E006MaskIncompleteAlarm, HardConstraintError
from . import Services


def run(state: dict, svc: Services) -> dict:
    diag = state.get("diagnostic") or {}
    prompts = (diag.get("action_params") or {}).get("points", [])
    masks = svc.gateway.call(
        "sam", svc.sam.segment, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], prompts=prompts,
    )
    for m in masks:  # 硬约束：必须为掩膜，禁 bbox 切割
        if not m.get("mask_rle"):
            raise HardConstraintError("mask 必须为掩膜(RLE)，禁 bbox")
    if any(m.get("incomplete") for m in masks):
        raise E006MaskIncompleteAlarm("共享基准线致掩膜残缺")
    return {"masks": masks, "status": "SEG_DIAGNOSED"}

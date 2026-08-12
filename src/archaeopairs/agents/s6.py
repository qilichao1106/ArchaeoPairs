"""S6 视觉分割器（§4.6）。Node: SAM 掩膜分割（掩膜三件套，禁 bbox）。

整改：消费 S9 指导信号（提示点/阈值）做针对性二次分割；掩膜残缺触发 E006。
"""
from __future__ import annotations

from ..errors import E004ScaleNoSeqAlarm, E006MaskIncompleteAlarm, HardConstraintError
from . import Services
from .alarms import assign_scales


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
        raise E006MaskIncompleteAlarm("shared baseline incomplete")
    seqs = [str(m.get("seq")) for m in masks if m.get("seq")]
    scale_map, scale_alarms = assign_scales(state.get("scale_annotations", []), seqs)
    if scale_alarms:
        raise E004ScaleNoSeqAlarm("multi-scale without seq no hard match")
    hard = {v for v in scale_map.values() if v != "shared"}
    shared = "shared" in scale_map.values()
    for m in masks:
        m["scale_level"] = 1 if str(m.get("seq")) in hard else 2 if shared else 3
    return {"masks": masks, "status": "SEG_DIAGNOSED"}

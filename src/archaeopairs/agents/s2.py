"""S2 图类判定器（§4.2）。Node: 视觉+XML 图题关键词判 image_type。

VLM 不可用（E1000）时按服务级降级与熔断（§3.7）退化为图题关键词规则：
地层特例通过"无平面/剖面否决词"近似实现（关键词兜底无法看像素，
含地层/遗迹且无否决词的图保守判 line_drawing，由后续 S5 报警兜底）。
"""
from __future__ import annotations

from ..errors import E1000ServiceUnavailableError
from ..parsers.keywords import classify_caption, refine_image_type
from . import Services


def run(state: dict, svc: Services) -> dict:
    try:
        resp = svc.gateway.call(
            "vlm", svc.vlm.classify, figure_id=state["figure_id"], trace_id=state["trace_id"],
            image_ref=state["fileref"], caption=state.get("caption"),
            figure_note=state.get("figure_note"),
            operation="classify", iteration=state.get("iteration", 0),
            cost=svc.thresholds.model_costs.get("vlm", 0.0),
        )
        itype = refine_image_type(resp["image_type"], state.get("caption"), state.get("figure_note"))
        if itype in {"discarded", "plate_scene", "multi_plate"}:
            return {"image_type": itype, "status": "EXCLUDED", "exclude_reason": "discarded_archived"}
        return {"image_type": itype, "status": "CLASSIFIED"}
    except E1000ServiceUnavailableError:
        # §3.7 服务级降级：关键词兜底
        itype = classify_caption(state.get("caption"), has_items=False)
        return {"image_type": itype, "status": "CLASSIFIED", "classify_fallback": True}

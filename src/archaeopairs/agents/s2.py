"""S2 图类判定器（§4.2，V0.4.1）。Node: 以 XML 器物号 + 关键词判 image_type（五分类）。

判定为确定性、无 VLM：XML 器物号个数（图注∪图题）为主信号，
线/彩家族由关键词 图版/圖版 判定。三五一树走后整图归属链，
其余（multi_plate_artifact / discarded）归档不构配。
"""
from __future__ import annotations

from ..parsers.keywords import decide_image_class
from . import Services


def run(state: dict, svc: Services) -> dict:
    itype = decide_image_class(state.get("caption"), state.get("figure_note"))
    if itype in {"discarded", "multi_plate_artifact"}:
        return {"image_type": itype, "status": "EXCLUDED", "exclude_reason": "discarded_archived"}
    return {"image_type": itype, "status": "CLASSIFIED"}

"""S2 图类判定器（§4.2，V0.4.1）。Node: 只调用 classify_image_type 得五分类，不做内部识别。

判定确定性、无 VLM；XML 器物号（N）主判 + 像素/关键词定线彩家族，全部封装在
`parsers.image_classify.classify_image_type`。multi_plate / discarded 归档不构配。
"""
from __future__ import annotations

from pathlib import Path

from ..parsers.image_classify import classify_image_type
from . import Services


def run(state: dict, svc: Services) -> dict:
    image_path = None
    if state.get("fileref") and state.get("image_base"):
        image_path = Path(str(state["image_base"])) / str(state["fileref"])
    itype = classify_image_type(state.get("caption"), state.get("figure_note"), image_path)
    if itype in {"discarded", "multi_plate_artifact"}:
        return {"image_type": itype, "status": "EXCLUDED", "exclude_reason": "discarded_archived"}
    return {"image_type": itype, "status": "CLASSIFIED"}

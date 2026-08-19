"""S2 图类判定器（§4.2，V0.5.3）。Node: 只调用 classify_image_type 得五分类，不做内部识别。

判定确定性、无 VLM；XML 器物号（N）主判 + 像素/关键词定线彩家族，全部封装在
`parsers.image_classify.classify_image_type`。multi_plate / discarded 归档不构配；
multi_line 走 S3~S6 主通路（V0.5.3 恢复，不再跳 multi_line_skipped）。
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

    # 单器物分状态：线图 CLASSIFIED_SINGLE_LINE / 彩图 CLASSIFIED_PLATE（§6.2）
    if itype == "single_line_artifact":
        return {"image_type": itype, "status": "CLASSIFIED_SINGLE_LINE"}
    if itype == "single_plate_artifact":
        return {"image_type": itype, "status": "CLASSIFIED_PLATE"}
    # 多器物线图：进入 S3~S6 主通路（V0.5.3 恢复，经 route_classify → parse_text/parse_image）
    return {"image_type": itype, "status": "CLASSIFIED"}

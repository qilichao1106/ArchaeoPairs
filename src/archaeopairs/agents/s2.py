"""S2 图类判定器（§4.2，V0.5.1）。Node: 只调用 classify_image_type 得五分类，不做内部识别。

判定确定性、无 VLM；XML 器物号（N）主判 + 像素/关键词定线彩家族，全部封装在
`parsers.image_classify.classify_image_type`。multi_plate / discarded 归档不构配；
multi_line 临时试点跳到 multi_line_skipped（见下方 TEMP），协助在其它类别上验证。
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

    # TEMP(skip multi_line, 2026-08-18)：临时试点先不处理多器物线图（S3~S6），
    # 仅在其它类别（single_* / multi_plate / discarded）上验证；MULTI_LINE_SKIPPED
    # 为试点临时态（归档留痕、可统计、可恢复，恢复后重入 S2 判定）。
    # 恢复时删除本节并取消 routing.route_classify 中 multi_line 分发分支的注释。
    if itype == "multi_line_artifact":
        return {"image_type": itype, "status": "MULTI_LINE_SKIPPED",
                "exclude_reason": "multi_line_skipped"}

    # 单器物分状态：线图 CLASSIFIED_SINGLE_LINE / 彩图 CLASSIFIED_PLATE（§6.2）
    status = "CLASSIFIED_SINGLE_LINE" if itype == "single_line_artifact" else "CLASSIFIED_PLATE"
    return {"image_type": itype, "status": status}

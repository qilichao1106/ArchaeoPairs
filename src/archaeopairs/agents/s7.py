"""S7 彩板解析器（§4.7）。Node: 器物彩板→单张彩图 Pair；场景照归 discarded。

整改：提取图版号；区分 plate_artifact / plate_scene；条目→artifact_id 用 ground。
"""
from __future__ import annotations

import re

from .. import naming
from ..parsers import s3_note
from . import Services

_PLATE_NO_RE = re.compile(r"(图版|圖版)\s*([0-9]+|[一二三四五六七八九十百千]+)")


def run(state: dict, svc: Services) -> dict:
    if state.get("image_type") == "plate_scene":
        return {"pair_records": [], "assembled": True, "status": "EXCLUDED",
                "exclude_reason": "plate_scene_discarded"}
    caption = state.get("caption") or ""
    m = _PLATE_NO_RE.search(caption)
    plate_no = f"{m.group(1)}{m.group(2)}" if m else naming.extract_fig_number(caption)
    items = s3_note.parse_note(state.get("figure_note") or "")
    arts = [a for it in items for a in it.artifact_ids]
    if not arts:
        arts = [a for a in dict.fromkeys(t.get("artifact_id", "") for t in state.get("text_artifacts", [])) if a]
    if not arts:
        return {"pair_records": [], "assembled": True, "status": "PENDING_REVIEW",
                "exclude_reason": "plate_artifact_id_missing"}
    records = [{
        "book_id": state["book_id"],
        "artifact_id": a,
        "image_path": f"{plate_no}_{naming.path_artifact(a)}.png",
        "provenance": {"type": "plate", "plate_no": plate_no},
    } for a in arts]
    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

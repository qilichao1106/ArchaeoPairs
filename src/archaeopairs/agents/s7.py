"""S7 彩板解析器（§4.7）。Node: 器物彩板→单张彩图 Pair；场景照归 discarded。

整改：提取图版号；区分 plate_artifact / plate_scene；条目→artifact_id 用 ground。
"""
from __future__ import annotations

import re

from .. import naming
from . import Services

_PLATE_NO_RE = re.compile(r"(图版|圖版)\s*([0-9]+|[一二三四五六七八九十百千]+)")


def run(state: dict, svc: Services) -> dict:
    if state.get("image_type") == "plate_scene":
        return {"pair_records": [], "assembled": True, "status": "EXCLUDED",
                "exclude_reason": "plate_scene_discarded"}
    caption = state.get("caption") or ""
    m = _PLATE_NO_RE.search(caption)
    plate_no = f"{m.group(1)}{m.group(2)}" if m else naming.extract_fig_number(caption)
    g = svc.ground.get(state["figure_id"], {})
    arts = g.get("artifact_ids") or [state["figure_id"].split(":")[-1]]
    records = [{
        "book_id": state["book_id"],
        "artifact_id": a,
        "image_path": f"{plate_no}_{naming.path_artifact(a)}.png",
        "provenance": {"type": "plate", "plate_no": plate_no},
    } for a in arts]
    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

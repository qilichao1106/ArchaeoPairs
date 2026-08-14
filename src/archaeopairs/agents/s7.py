"""S7 彩板解析器（§4.7）。Node: 器物彩板→单张彩图 Pair；场景照归 discarded。

整改：图版号正则补 O/〇 归一与拓片样式；条目→artifact_id 优先 XML 图注（链①），
缺失时以链② text_artifacts 兜底；产出统一经 PairRecord（含 description_text）。
"""
from __future__ import annotations

import re

from .. import naming
from ..parsers import s3_note
from ..state import PairRecord
from . import Services

_PLATE_NO_RE = re.compile(r"(图版|圖版|拓片)\s*([0-9〇O一二三四五六七八九十百千]+)")


def plate_no_of(caption: str | None, fallback: str = "") -> str:
    m = _PLATE_NO_RE.search(caption or "")
    if m:
        num = m.group(2).replace("O", "〇")
        return f"{m.group(1)}{num}"
    return naming.extract_fig_number(caption, fallback=fallback)


def run(state: dict, svc: Services) -> dict:
    if state.get("image_type") == "plate_scene":
        return {"pair_records": [], "assembled": True, "status": "EXCLUDED",
                "exclude_reason": "plate_scene_discarded"}
    caption = state.get("caption") or ""
    plate_no = plate_no_of(caption, fallback=naming.extract_fig_number(caption))
    items = s3_note.parse_note(state.get("figure_note") or "")
    arts = [a for it in items for a in it.artifact_ids]
    if not arts:
        arts = [a for a in dict.fromkeys(t.get("artifact_id", "") for t in state.get("text_artifacts", [])) if a]
    if not arts:
        return {"pair_records": [], "assembled": True, "status": "PENDING_REVIEW",
                "exclude_reason": "plate_artifact_id_missing"}
    desc = {t.get("artifact_id"): t.get("text") for t in state.get("text_artifacts", [])}
    records = [PairRecord(
        book_id=state["book_id"],
        artifact_id=a,
        image_path=f"{plate_no}_{naming.path_artifact(a)}.png",
        candidate_images=[],
        image_merge_mode="plate_only",
        description_text=desc.get(a),
        provenance={"type": "plate", "plate_no": plate_no},
    ).model_dump() for a in arts]
    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

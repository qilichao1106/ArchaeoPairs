"""S7 single-artifact parser (V0.4 §4.7).

Single-artifact line drawings and single-artifact plates are whole-image
Pairs: resolve artifact_id from figure-note/caption, attach body text, and
hand the candidate to S8 for Pair assembly. Multi-artifact plates, scene
plates and discarded figures are archived without Pair construction.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import naming
from ..parsers import s3_note, s3_text
from . import Services
from . import s3 as s3_agent

_PLATE_NO_RE = re.compile(r"(图版|圖版|拓片)\s*([0-9〇O一二三四五六七八九十百千]+)")


def plate_no_of(caption: str | None, fallback: str = "") -> str:
    m = _PLATE_NO_RE.search(caption or "")
    if m:
        num = m.group(2).replace("O", "〇")
        return f"{m.group(1)}{num}"
    return naming.extract_fig_number(caption, fallback=fallback)


def _resolve_artifact(state: dict, caption: str) -> tuple[list[str], str]:
    items = s3_note.parse_note(state.get("figure_note") or "")
    arts = [a for it in items for a in it.artifact_ids]
    source = "figure_note"
    if not arts:
        arts = s3_note.extract_caption_artifacts(caption)
        source = "caption"
    if not arts:
        arts = [a for a in dict.fromkeys(t.get("artifact_id", "") for t in state.get("text_artifacts", [])) if a]
        source = "text"
    return list(dict.fromkeys(arts)), source


def run(state: dict, svc: Services) -> dict:
    itype = state.get("image_type")
    if itype in {"discarded", "multi_plate_artifact"}:
        return {"pair_records": [], "assembled": True, "status": "EXCLUDED",
                "exclude_reason": "discarded_archived"}
    caption = state.get("caption") or ""
    arts, source = _resolve_artifact(state, caption)
    if not arts:
        return {"pair_records": [], "assembled": True, "status": "PENDING_REVIEW",
                "exclude_reason": "single_artifact_id_missing"}
    if len(arts) > 1:
        return {"pair_records": [], "assembled": True, "status": "PENDING_REVIEW",
                "alarms": ["E005"], "exclude_reason": "multi_artifact_on_single_path"}

    art = arts[0]
    is_line = itype == "single_line_artifact"
    role = "line_drawing" if is_line else "plate"
    fig_fallback = Path(state["fileref"]).stem
    fig_number = (plate_no_of(caption, fallback=fig_fallback) if not is_line
                  else naming.extract_fig_number(caption, fallback=fig_fallback))
    paras = s3_agent.select_paras(state.get("body_paras", []), {art}, fig_number)
    text_artifacts = [
        t.model_dump()
        for t in s3_text.split_body([(p.get("id", ""), p.get("text", "")) for p in paras])
    ]
    return {
        "single_artifacts": [{
            "artifact_id": art,
            "source": source,
            "role": role,
            "image_merge_mode": "line_only" if is_line else "plate_only",
            "figure_id": state["figure_id"],
            "fig_number": fig_number,
        }],
        "text_artifacts": text_artifacts,
        "degraded": source == "caption",
        "case_type": "single_line_artifact" if is_line else "single_plate_artifact",
        "status": "CLASSIFIED" if is_line else "CLASSIFIED_PLATE",
        "assembled": False,
    }

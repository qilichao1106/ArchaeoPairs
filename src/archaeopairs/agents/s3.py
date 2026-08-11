"""S3 文本源解析器（§4.3）。Node: 图注语法解析(链①)+正文切分(链②)。"""
from __future__ import annotations

from ..parsers import s3_note
from . import Services


def run(state: dict, svc: Services) -> dict:
    note_items = s3_note.parse_note(state.get("figure_note") or "")
    return {
        "note_items": [n.model_dump() for n in note_items],
        "text_artifacts": state.get("text_artifacts", []),
    }

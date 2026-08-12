"""S3 文本源解析器（§4.3）。Node: 图注语法解析(链①)+正文切分(链②)。

链②真正进入管线：对 book 正文段落做 artifact_id 切分，产出 text_artifacts。
"""
from __future__ import annotations

from ..parsers import s3_note, s3_text
from . import Services


def run(state: dict, svc: Services) -> dict:
    note_items = s3_note.parse_note(state.get("figure_note") or "")
    paras = [(p.get("id", ""), p.get("text", "")) for p in state.get("body_paras", [])]
    text_artifacts = s3_text.split_body(paras)
    return {
        "note_items": [n.model_dump() for n in note_items],
        "text_artifacts": [t.model_dump() for t in text_artifacts],
    }

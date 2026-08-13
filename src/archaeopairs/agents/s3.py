"""S3 文本源解析器（§4.3）。Node: 图注语法解析(链①)+正文切分(链②)。

链②真正进入管线：对 book 正文段落做 artifact_id 切分，产出 text_artifacts。
"""
from __future__ import annotations

from .. import naming
from ..parsers import s3_note, s3_text
from . import Services


def run(state: dict, svc: Services) -> dict:
    note_items = s3_note.parse_note(state.get("figure_note") or "")
    note_arts = {a for it in note_items for a in it.artifact_ids}
    body_paras = state.get("body_paras", [])
    fig_number = naming.extract_fig_number(state.get("caption"))

    # 图注缺失时，只处理引用当前图号的正文段落，避免每张图切分整本书。
    if note_arts:
        paras = [(p.get("id", ""), p.get("text", "")) for p in body_paras
                 if any(a in p.get("text", "") for a in note_arts)]
    elif fig_number:
        paras = [(p.get("id", ""), p.get("text", "")) for p in body_paras
                 if fig_number in p.get("text", "")]
    else:
        paras = []

    text_artifacts = s3_text.split_body(paras)

    if svc.flags.s3_llm_confirm:
        for item in text_artifacts:
            if item.markers and item.confidence < 0.7:
                resp = svc.gateway.call(
                    "vlm", svc.vlm.confirm_text,
                    figure_id=state["figure_id"], trace_id=state["trace_id"],
                    operation="confirm_text", iteration=state.get("iteration", 0),
                    cost=svc.thresholds.model_costs.get("vlm", 0.0),
                    artifact_id=item.artifact_id, text=item.text,
                    context={"figure_number": fig_number, "markers": item.markers},
                )
                if resp.get("accepted"):
                    item.confidence = max(item.confidence, float(resp.get("confidence", 0.9)))
                    item.markers.append("llm_confirmed")

    return {
        "note_items": [n.model_dump() for n in note_items],
        "text_artifacts": [t.model_dump() for t in text_artifacts],
    }

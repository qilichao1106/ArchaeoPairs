"""S3 文本源解析器（§4.3）。Node: 图注语法解析(链①)+正文切分(链②)。

链②真正进入管线：对 book 正文段落做 artifact_id 切分，产出 text_artifacts。
正文筛选先归一化再匹配（修复全角冒号失配），图号引用按 canonical 形式匹配
（"图二六O" 与 "图二六〇" 等价）。

图题器物号兜底（图题器物号兜底识别（§2.2.5））：图注缺失或解析不出器物号时，
从图题纯扫描抽取器物号（单器物图其号常仅在图题中），参与正文筛选并交 S5 仲裁。
"""
from __future__ import annotations

from .. import naming
from ..parsers import s3_note, s3_text
from . import Services


def select_paras(body_paras: list[dict], note_arts: set[str], fig_number: str) -> list[dict]:
    """按 器物号集合 / 图号 从正文段落中筛选相关段落（CLI 预筛选与节点内复用）。

    器物号匹配在归一化文本上进行（双侧同归一：圈号→数字、冒号→半角），
    保证 "2004CWWM11：5"（正文）命中 "2004CWWM11:5"（图注键）。
    """
    canon = naming.canonical_fig_text(fig_number) if fig_number else ""
    note_arts_norm = {s3_note.normalize(a) for a in note_arts}
    out: list[dict] = []
    for p in body_paras:
        text = p.get("text", "")
        if not text:
            continue
        if note_arts_norm:
            tn = s3_note.normalize(text)
            if any(a in tn for a in note_arts_norm):
                out.append(p)
        elif canon:
            if canon in naming.canonical_fig_text(text):
                out.append(p)
        # 无图号无器物号：不取正文（链②不可判定，交由 S5 降级矩阵）
    return out


def run(state: dict, svc: Services) -> dict:
    note_items = s3_note.parse_note(state.get("figure_note") or "")
    note_arts = {a for it in note_items for a in it.artifact_ids}
    # 图题器物号兜底（§2.2.5）：仅当图注解析不出器物号时启用；链①有号则以链①为准
    caption_arts = [] if note_arts else s3_note.extract_caption_artifacts(state.get("caption"))
    body_paras = state.get("body_paras", [])
    fig_number = naming.extract_fig_number(state.get("caption"))

    paras = select_paras(body_paras, note_arts | set(caption_arts), fig_number)
    text_artifacts = s3_text.split_body([(p.get("id", ""), p.get("text", "")) for p in paras])

    # 低置信度产物（confidence < 0.7）直接抛弃，不再交由 VLM 确认
    text_artifacts = [t for t in text_artifacts if t.confidence >= 0.7]

    return {
        "note_items": [n.model_dump() for n in note_items],
        "caption_artifacts": caption_arts,
        "text_artifacts": [t.model_dump() for t in text_artifacts],
    }

"""S3 正文切分（对齐《技术方案 V0.5.1》正文切分决策树（§4.3.2））。

按 artifact_id 锚点切分描述段。规则：单锚点整段归属；多锚点按"标本X:1，"
边界切分；无锚点按件数语/标本号/图引用/最近上文归并；低置信段标记待 LLM
确认（受 s3_llm_confirm 控制）。

锚点在归一化文本上匹配、按 1:1 span 回映原文（冒号归一、圈号保留原文），
保证正文侧 artifact_id 与图注侧键值一致。
"""
from __future__ import annotations

import re

from ..state import TextArtifact
from .s3_note import ARTIFACT_RE, colon_norm, normalize


def _anchor_of(raw: str, m: re.Match) -> str:
    return colon_norm(raw[m.start():m.end()])


def split_body(paragraphs: list[tuple[str, str]]) -> list[TextArtifact]:
    """paragraphs: [(para_id, text)] -> TextArtifact 列表。"""
    out: list[TextArtifact] = []
    last_anchor: str | None = None
    for pid, raw in paragraphs:
        text = normalize(raw)
        anchors = list(ARTIFACT_RE.finditer(text))
        if anchors:
            if len(anchors) == 1:
                m = anchors[0]
                out.append(TextArtifact(artifact_id=_anchor_of(raw, m), text=raw,
                                        source_para_ids=[pid], confidence=0.95))
                last_anchor = _anchor_of(raw, m)
            else:
                for idx, m in enumerate(anchors):
                    start = m.start()
                    end = anchors[idx + 1].start() if idx + 1 < len(anchors) else len(raw)
                    seg = raw[start:end].strip()
                    out.append(TextArtifact(artifact_id=_anchor_of(raw, m), text=seg,
                                            source_para_ids=[pid], markers=["multi_anchor"],
                                            confidence=0.8))
                last_anchor = _anchor_of(raw, anchors[-1])
        else:
            markers: list[str] = []
            conf = 0.6
            if re.search(r"\d+\s*件", text):
                markers.append("piece_count")
            elif re.search(r"图\s*[\d一二三四五六七八九十〇]+", text):
                markers.append("fig_ref")
            else:
                markers.append("no_anchor")
            target = last_anchor
            if target is None:
                continue
            out.append(TextArtifact(artifact_id=target, text=raw, source_para_ids=[pid],
                                    markers=markers, confidence=conf))
    return out

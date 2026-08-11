"""S3 正文切分（对齐《技术方案 V0.1》§4.3.2 决策树）。

按 artifact_id 锚点切分描述段。规则：单锚点整段归属；多锚点按"标本X:1，"
边界切分；无锚点按件数语/标本号/图引用/最近上文归并；低置信段标记待 LLM
确认（受 s3_llm_confirm 控制）。
"""
from __future__ import annotations

import re

from ..state import TextArtifact
from .s3_note import ARTIFACT_RE, normalize


def split_body(paragraphs: list[tuple[str, str]]) -> list[TextArtifact]:
    """paragraphs: [(para_id, text)] -> TextArtifact 列表。"""
    out: list[TextArtifact] = []
    last_anchor: str | None = None
    for pid, raw in paragraphs:
        text = normalize(raw)
        anchors = ARTIFACT_RE.findall(text)
        if anchors:
            if len(anchors) == 1:
                out.append(TextArtifact(artifact_id=anchors[0], text=raw,
                                        source_para_ids=[pid], confidence=0.95))
                last_anchor = anchors[0]
            else:
                # 多锚点：按锚点切分（简化：每个锚点一条，文本共享）
                for a in anchors:
                    out.append(TextArtifact(artifact_id=a, text=raw,
                                            source_para_ids=[pid], markers=["multi_anchor"],
                                            confidence=0.8))
                last_anchor = anchors[-1]
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

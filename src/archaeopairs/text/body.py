"""Body-text splitting by artifact-id anchors (R-OUT-03).

``split_body`` attributes body paragraphs to artifact ids:

* A paragraph with one anchor -> its whole text belongs to that artifact
  (``markers=["single_anchor"]``).
* A paragraph with several anchors is cut at ``标本X:1，……`` boundaries; each
  artifact keeps its own slice (``markers=["multi_anchor"]``).
* A paragraph with no anchor is hung on the nearest preceding anchor
  (``markers=["no_anchor"]``); if none exists it is dropped, not guessed.

No LLM confirmation is performed here.
"""

from __future__ import annotations

import re

from archaeopairs.models import TextArtifact
from archaeopairs.text.artifact_id import extract_artifacts, normalize_artifact_id

# Anchor occurrence used to locate cuts; the groups mirror ``artifact_id``.
_ANCHOR_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<pre>[A-Za-z]{0,4}\d[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)"
    r"(?P<groups>(?:[:\uff1a\u2236][A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)+)"
    r"(?![A-Za-z0-9])"
)
# A new ``标本`` specimen marker is a natural slice boundary (spec A.1).
_SPECIMEN_RE = re.compile(r"标本")
_SENTENCE_END_RE = re.compile(r"[。；;]\s*")


def _para_fields(para: tuple[str, str] | dict) -> tuple[str, str]:
    if isinstance(para, dict):
        pid = para.get("id") or para.get("para_id") or para.get("source_para_id") or ""
        text = para.get("text") or ""
        return str(pid), str(text)
    pid, text = para
    return str(pid), str(text)


def _anchors(text: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for match in _ANCHOR_RE.finditer(text):
        if not re.search(r"[A-Za-z]", match.group("pre")):
            continue
        groups = re.split(r"[:\uff1a\u2236]", match.group("groups"))
        for group in groups:
            if group:
                hits.append((match.start(), normalize_artifact_id(match.group("pre") + ":" + group)))
    # Deduplicate on (offset) while preserving order.
    seen: set[int] = set()
    ordered: list[tuple[int, str]] = []
    for offset, aid in sorted(hits):
        if offset not in seen:
            seen.add(offset)
            ordered.append((offset, aid))
    return ordered


def _cut(text: str, anchors: list[tuple[int, str]]) -> list[tuple[str, str]]:
    """Split one multi-anchor paragraph at specimen/sentence boundaries."""

    slices: list[tuple[str, str]] = []
    for idx, (offset, aid) in enumerate(anchors):
        if idx + 1 < len(anchors):
            look = text[offset:anchors[idx + 1][0]]
            sentence = list(_SENTENCE_END_RE.finditer(look))
            # Slice ends at the sentence terminator that precedes the next
            # anchor; the trailing fragment then opens the next artifact.
            stop = offset + sentence[-1].end() if sentence else anchors[idx + 1][0]
        else:
            stop = len(text)
        segment = re.sub(r"[\s，,、；;。]+$", "", text[offset:stop].strip())
        if segment:
            slices.append((aid, segment))
    return slices


def split_body(paras: list[tuple[str, str] | dict]) -> list[TextArtifact]:
    """Attribute body paragraphs to artifact ids in first-seen order."""

    groups: dict[str, dict] = {}
    order: list[str] = []
    last_aid: str | None = None

    def attach(aid: str, text: str, pid: str, marker: str) -> None:
        slot = groups.get(aid)
        if slot is None:
            slot = {"parts": [], "texts": [], "markers": []}
            groups[aid] = slot
            order.append(aid)
        slot["parts"].append(pid)
        slot["texts"].append(text)
        if marker not in slot["markers"]:
            slot["markers"].append(marker)

    for para in paras:
        pid, text = _para_fields(para)
        if not text.strip():
            continue
        anchors = _anchors(text)
        if not anchors:
            if last_aid is not None:
                attach(last_aid, text.strip(), pid, "no_anchor")
            continue
        if len(anchors) == 1:
            aid = anchors[0][1]
            body = text.strip()
            attach(aid, body, pid, "single_anchor")
            last_aid = aid
            continue
        for aid, segment in _cut(text, anchors):
            attach(aid, segment, pid, "multi_anchor")
        last_aid = anchors[-1][1]

    out: list[TextArtifact] = []
    for aid in order:
        slot = groups[aid]
        out.append(
            TextArtifact(
                artifact_id=aid,
                text="\n".join(slot["texts"]),
                source_para_ids=_unique(slot["parts"]),
                markers=list(slot["markers"]),
            )
        )
    return out


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
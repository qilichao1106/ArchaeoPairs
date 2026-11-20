"""T-003 negative controls: noise must never be guessed into a mapping.

Each test feeds input that carries no usable artifact evidence and asserts the
empty/conflict outcome.  These are the negative counterparts of the positive
cardinality tests; a "guess everything" regression must turn them red.
"""

from __future__ import annotations

from archaeopairs.mapping.text_map import build_text_mapping
from archaeopairs.text.artifact_id import extract_artifacts
from archaeopairs.text.body import split_body
from archaeopairs.text.note import extract_caption_artifacts, parse_note


def test_negative_scale_and_figure_numbers_are_not_artifact_ids():
    for text in ("0 8厘米", "比例尺 0 8厘米", "图二一二", "图2-1-16", "图版三 铜舟"):
        assert extract_artifacts(text) == []
    assert parse_note("0 8厘米") == []
    assert extract_caption_artifacts("图版204") == []
    assert extract_caption_artifacts(None) == []


def test_negative_bare_prefixed_name_is_evidence_only():
    """``Bb9`` has no colon: it may name an artifact, it never creates an id."""
    assert extract_artifacts("Bb9") == []
    assert extract_artifacts("Bb9 陶豆") == []
    item = parse_note("A. 盗坑（长沙青振）")[0]
    assert item.artifact_ids == []


def test_negative_count_mismatch_is_a_conflict_not_a_pairing():
    mapping = build_text_mapping(parse_note("1、2. 陶豆（M4:1、M4:2、M4:3）"), [], [])
    assert mapping.seq_to_artifacts == {}
    assert any(
        conflict.startswith("cardinality_mismatch:") for conflict in mapping.conflicts
    )


def test_negative_text_without_seq_or_artifact_yields_nothing():
    for text in ("", "   ", "这段说明没有序号也没有器物号。", "比例尺 0 8厘米"):
        assert parse_note(text) == []


def test_negative_unattributable_body_paragraph_is_dropped():
    artifacts = split_body(
        [
            ("p0", "无器物号的开篇说明。"),
            ("p1", "标本M4:1，陶豆。"),
        ]
    )
    assert [artifact.artifact_id for artifact in artifacts] == ["M4:1"]
    assert all("无器物号" not in artifact.text for artifact in artifacts)
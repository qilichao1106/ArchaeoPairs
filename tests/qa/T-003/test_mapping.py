"""T-003 seq -> artifact text mapping (card §4, R-MAP-01..07, AC-02).

Frozen expectations:

* figure note first, caption title only as the weak fallback, ``seq_missing``
  when neither yields an id;
* four cardinalities: 1:1, N:1 (``rule_b``), 1:N (``split_same_seq``),
  N:N positional zip (``rule_a``, or ``range_split`` for a range seq);
* count mismatches and one artifact claimed by several seqs are conflicts, with
  no Cartesian product and no guessed pairing.
"""

from __future__ import annotations

from archaeopairs.mapping.text_map import build_text_mapping
from archaeopairs.models import TextArtifact
from archaeopairs.text.note import extract_caption_artifacts, parse_note


def _map(note: str, caption: str | None = None):
    return build_text_mapping(parse_note(note), extract_caption_artifacts(caption), [])


def test_one_seq_one_artifact_is_rule_a():
    mapping = _map("1. 骨笄（M4:1）")
    assert mapping.seq_to_artifacts == {"1": ["M4:1"]}
    assert mapping.case_type == "rule_a"
    assert mapping.caption_artifacts == []
    assert mapping.conflicts == []


def test_n_seq_one_artifact_is_rule_b():
    mapping = _map("4、6、7. 串珠（M1:29）")
    assert mapping.seq_to_artifacts == {
        "4": ["M1:29"],
        "6": ["M1:29"],
        "7": ["M1:29"],
    }
    assert mapping.case_type == "rule_b"
    assert mapping.conflicts == []


def test_one_seq_many_artifacts_is_split_same_seq():
    mapping = _map("1. 陶豆（M4:1、M4:2）")
    assert mapping.seq_to_artifacts == {"1": ["M4:1", "M4:2"]}
    assert mapping.case_type == "split_same_seq"
    assert mapping.conflicts == []


def test_n_seq_n_artifact_positional_zip_is_rule_a():
    mapping = _map("1、2. 陶豆（M4:2、M4:1）")
    assert mapping.seq_to_artifacts == {"1": ["M4:2"], "2": ["M4:1"]}
    assert mapping.case_type == "rule_a"
    assert "1、2" not in mapping.seq_to_artifacts
    assert mapping.conflicts == []


def test_n_seq_n_artifact_range_zip_is_range_split():
    mapping = _map("1～4.豆（M3:4、M3:2、M3:3、M3:1）")
    assert mapping.seq_to_artifacts == {
        "1": ["M3:4"],
        "2": ["M3:2"],
        "3": ["M3:3"],
        "4": ["M3:1"],
    }
    assert mapping.case_type == "range_split"
    assert mapping.conflicts == []


def test_figure_note_wins_over_caption_title():
    mapping = build_text_mapping(
        parse_note("1. 骨笄（M4:1）"),
        extract_caption_artifacts("图一 骨笄（M9:9）"),
        [],
    )
    assert mapping.seq_to_artifacts == {"1": ["M4:1"]}
    assert mapping.caption_artifacts == []
    assert mapping.conflicts == []
    assert all("M9:9" not in ids for ids in mapping.seq_to_artifacts.values())


def test_caption_title_is_the_fallback_when_note_has_no_id():
    mapping = build_text_mapping(
        parse_note("1. 陶豆 2. 陶壶"),
        extract_caption_artifacts("图五 陶豆（M4:1、M4:2）"),
        [],
    )
    assert mapping.seq_to_artifacts == {"1": ["M4:1"], "2": ["M4:2"]}
    assert mapping.case_type == "rule_a"
    assert mapping.caption_artifacts == []
    assert mapping.conflicts == []


def test_missing_note_and_caption_degrade_to_seq_missing():
    mapping = build_text_mapping(parse_note("1. 陶豆 2. 陶壶"), [], [])
    assert mapping.case_type == "seq_missing"
    assert mapping.seq_to_artifacts == {"1": [], "2": []}
    assert mapping.caption_artifacts == []
    assert mapping.conflicts == []


def test_count_mismatch_is_a_conflict_and_never_paired():
    mapping = _map("1、2. 陶豆（M4:1、M4:2、M4:3）")
    assert mapping.seq_to_artifacts == {}
    assert any(
        conflict.startswith("cardinality_mismatch:") for conflict in mapping.conflicts
    )
    assert all(
        "M4:" not in artifact
        for ids in mapping.seq_to_artifacts.values()
        for artifact in ids
    )


def test_same_artifact_on_two_seqs_is_a_conflict_but_evidence_is_kept():
    mapping = _map("1. 陶豆（M4:1） 2. 陶壶（M4:1）")
    assert mapping.seq_to_artifacts == {"1": ["M4:1"], "2": ["M4:1"]}
    assert any(
        conflict.startswith("artifact_claimed_by_multiple_seqs:M4:1:")
        for conflict in mapping.conflicts
    )


def test_body_only_artifact_is_recorded_not_paired_with_a_seq():
    body = [
        TextArtifact(
            artifact_id="M9:9",
            text="正文未在图中出现。",
            source_para_ids=["p9"],
            markers=["single_anchor"],
        )
    ]
    mapping = build_text_mapping(parse_note("1. 骨笄（M4:1）"), [], body)
    assert mapping.seq_to_artifacts == {"1": ["M4:1"]}
    assert "body_artifact_unmapped:M9:9" in mapping.conflicts
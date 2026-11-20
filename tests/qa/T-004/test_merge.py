"""Frozen acceptance tests for ``merge_ocr_results`` (card section 4).

Duplicates collapse on (text, bbox).  The same text at a different bbox is
kept twice and reported under ``raw["conflicts"]``; the merged result is always
``source="hybrid"``.
"""

from __future__ import annotations

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr.base import merge_ocr_results


def _result(seqs=(), scales=(), texts=(), *, source="vlm", raw=None):
    return OcrResult(
        seqs=list(seqs),
        scales=list(scales),
        texts=list(texts),
        source=source,
        raw=raw or {},
    )


def test_identical_text_and_bbox_are_deduplicated_primary_order_wins():
    primary = _result(
        seqs=[
            SeqLabel(text="1", bbox=(1, 2, 3, 4)),
            SeqLabel(text="2", bbox=(5, 6, 7, 8)),
        ],
        source="vlm",
    )
    secondary = _result(
        seqs=[
            SeqLabel(text="2", bbox=(5, 6, 7, 8)),
            SeqLabel(text="3", bbox=(9, 10, 11, 12)),
        ],
        source="paddle",
    )

    merged = merge_ocr_results(primary, secondary)

    assert merged.source == "hybrid"
    assert [seq.text for seq in merged.seqs] == ["1", "2", "3"]
    assert merged.raw["conflicts"] == []
    assert merged.raw["primary"] == primary.model_dump()
    assert merged.raw["secondary"] == secondary.model_dump()


def test_same_bbox_with_different_text_is_not_deduplicated():
    primary = _result(seqs=[SeqLabel(text="1", bbox=(0, 0, 10, 10))])
    secondary = _result(
        seqs=[SeqLabel(text="2", bbox=(0, 0, 10, 10))], source="paddle"
    )

    merged = merge_ocr_results(primary, secondary)

    assert [(seq.text, seq.bbox) for seq in merged.seqs] == [
        ("1", (0, 0, 10, 10)),
        ("2", (0, 0, 10, 10)),
    ]
    assert merged.raw["conflicts"] == []


def test_same_text_at_different_bbox_is_kept_and_reported_as_a_conflict():
    primary = _result(
        seqs=[SeqLabel(text="1", bbox=(0, 0, 10, 10))], source="vlm"
    )
    secondary = _result(
        seqs=[SeqLabel(text="1", bbox=(20, 20, 30, 30))], source="paddle"
    )

    merged = merge_ocr_results(primary, secondary)

    assert merged.source == "hybrid"
    assert [seq.bbox for seq in merged.seqs] == [
        (0, 0, 10, 10),
        (20, 20, 30, 30),
    ]
    conflicts = merged.raw["conflicts"]
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["text"] == "1"
    assert conflict["reason"] == "same_text_different_bbox"
    assert conflict["bboxes"] == [[0, 0, 10, 10], [20, 20, 30, 30]]
    assert conflict["primary_source"] == "vlm"
    assert conflict["secondary_source"] == "paddle"


def test_scales_and_texts_are_merged_and_deduplicated():
    scale = ScaleBar(
        text="0 8厘米",
        bbox=(0, 0, 100, 10),
        value=8.0,
        unit="厘米",
        prefix_nos=["1"],
    )
    text = TextBlock(text="盖顶面纹饰", bbox=(5, 6, 105, 66))
    primary = _result(scales=[scale], texts=[text], source="vlm")
    secondary = _result(scales=[scale], texts=[text], source="paddle")

    merged = merge_ocr_results(primary, secondary)

    assert merged.source == "hybrid"
    assert merged.scales == [scale]
    assert merged.texts == [text]
    assert merged.raw["conflicts"] == []


def test_empty_results_merge_into_an_empty_hybrid_result():
    merged = merge_ocr_results(_result(source="vlm"), _result(source="paddle"))

    assert merged.source == "hybrid"
    assert merged.seqs == []
    assert merged.scales == []
    assert merged.texts == []
    assert merged.raw["conflicts"] == []
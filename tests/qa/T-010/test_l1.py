"""T-010 frozen acceptance: L1 multi-line orchestration.

Covers the card's L1 contract with synthetic line drawings and a fake OCR/writer:

* two numbered views + one scale bar with both prefixes -> two distinct Pairs,
  two PNGs, rule-A provenance, ledger rows and contract-valid names;
* 1 seq : N artifacts -> shared view/image asset, one PNG for two Pairs;
* no scale bar -> every Unit is ``review`` with ``no_scale`` (R-IMG-09);
* scale-bar and seq-label glyph views are filtered before mapping (R-IMG-08);
* no body text -> ``description_text=None`` + ``no_text`` review (R-OUT-04).
"""

from __future__ import annotations

from archaeopairs.models import ImageType, WorkLine
from archaeopairs.pipeline import PipelineConfig, process_book, process_figure
from archaeopairs.vision import segment_views

from t010_synthetic import (
    FakeOCR,
    FakeWriter,
    blank_image,
    figure,
    line_image,
    ocr_result,
    para,
    pair_rows,
    scale_bar,
    seq_label,
    validate_pair,
)

BOOK = "bookA"


def _two_artifacts_with_shared_scale(tmp_path):
    """Two numbered line views and one bar whose prefix list names both seqs."""
    path = line_image(
        tmp_path / "l1_two.png",
        boxes=[(30, 30, 90, 90), (160, 30, 220, 90)],
        bar=(20, 160, 280, 164),
    )
    ocr = ocr_result(
        seqs=[seq_label("1", (40, 40, 50, 50)), seq_label("2", (170, 40, 180, 50))],
        scales=[
            scale_bar(
                "0 5厘米",
                (15, 155, 285, 175),
                prefix_nos=["1", "2"],
                value=5.0,
                unit="厘米",
            )
        ],
    )
    fig = figure(
        path,
        caption="图一 出土器物",
        note="1. 陶豆（M4:1） 2. 陶壶（M4:2）",
        body=[
            para("p1", "陶豆标本M4:1，泥质灰陶。"),
            para("p2", "陶壶标本M4:2，夹砂灰陶。"),
        ],
    )
    return fig, ocr


def test_l1_two_artifacts_share_one_scale_bar(tmp_path) -> None:
    fig, ocr = _two_artifacts_with_shared_scale(tmp_path)
    writer = FakeWriter()

    results = process_book([fig], PipelineConfig(ocr=FakeOCR(ocr), writer=writer))

    assert len(results) == 1
    result = results[0]
    assert result.status == "output"
    assert result.image_type is ImageType.MULTI_LINE
    assert result.work_line is WorkLine.MULTI_LINE
    assert result.alarms == []
    assert result.conflicts == []
    assert result.artifact_map is not None
    assert result.artifact_map.case_type == "rule_a"
    assert result.artifact_map.unbound_views == []
    assert result.artifact_map.unbound_groups == []
    assert result.artifact_map.unbound_seqs == []

    pairs = result.pairs
    assert len(pairs) == 2
    assert [pair.artifact_id for pair in pairs] == ["M4:1", "M4:2"]
    assert [pair.image_path for pair in pairs] == [
        "图一_1_M4-1.png",
        "图一_2_M4-2.png",
    ]
    assert [pair.figure_number for pair in pairs] == ["图一", "图一"]

    for pair, artifact_id, seq_id, para_id in zip(
        pairs, ("M4:1", "M4:2"), ("1", "2"), ("p1", "p2"), strict=True
    ):
        assert pair.source_role == "line"
        assert pair.image_merge_mode == "line_only"
        assert pair.status == "output"
        assert pair.quality_flags == []
        assert pair.description_text is not None
        assert pair.description_text.startswith("陶")
        assert pair.text_length == len(pair.description_text)

        mapping = pair.provenance.mapping
        assert mapping.artifact_id == artifact_id
        assert mapping.seq_ids == [seq_id]
        assert len(mapping.view_ids) == 1
        assert mapping.scale_ids == [0]
        assert mapping.scale_sources == ["L1_prefix"]
        assert mapping.confidence == 1.0
        assert mapping.line == WorkLine.MULTI_LINE
        assert mapping.source_role == "line"
        assert pair.provenance.source_para_ids == [para_id]
        assert pair.provenance.art_source == "figure_note"
        assert pair.provenance.shared_group is None
        validate_pair(pair)

    # Writer saw one real PNG per Pair, and the book-level sinks were called once.
    assert [name for name, _shape in writer.images] == [p.image_path for p in pairs]
    assert all(len(shape) == 3 for _name, shape in writer.images)
    assert writer.write_pairs_calls == 1
    assert writer.write_ledger_calls == 1
    assert len(writer.pairs) == 2

    # Ledger pair rows carry the mapping facts needed for audit.
    rows = pair_rows(writer.ledger)
    assert len(rows) == 2
    for row, seq_id in zip(rows, ("1", "2"), strict=True):
        assert row["book_id"] == BOOK
        assert row["figure_id"] == fig.figure_id
        assert row["seq"] == seq_id
        assert row["view_ids"]
        assert row["scale_ids"] == [0]
        assert row["scale_sources"] == ["L1_prefix"]
        assert row["line"] == "multi_line"
        assert row["status"] == "output"
        assert row["alarms"] == []


def test_l1_one_seq_two_artifacts_share_one_view(tmp_path) -> None:
    """1 seq : N artifacts keeps one view image asset for two different Pairs."""
    path = line_image(
        tmp_path / "l1_shared.png",
        boxes=[(40, 30, 140, 100)],
        bar=(20, 160, 200, 164),
    )
    ocr = ocr_result(
        seqs=[seq_label("1", (50, 40, 60, 50))],
        scales=[
            scale_bar(
                "0 5厘米",
                (15, 155, 205, 175),
                prefix_nos=["1"],
                value=5.0,
                unit="厘米",
            )
        ],
    )
    fig = figure(
        path,
        caption="图二 出土器物",
        note="1. 陶豆（M4:1、M4:2）",
        body=[
            para("p1", "陶豆标本M4:1，泥质灰陶。"),
            para("p2", "陶壶标本M4:2，夹砂灰陶。"),
        ],
    )
    writer = FakeWriter()

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(ocr), writer=writer))

    assert result.status == "output"
    assert result.artifact_map is not None
    assert result.artifact_map.case_type == "split_same_seq"
    assert len(result.pairs) == 2
    first, second = result.pairs
    assert {first.artifact_id, second.artifact_id} == {"M4:1", "M4:2"}
    assert first.image_path == second.image_path == "图二_1_M4-1.png"
    assert first.provenance.mapping.view_ids == second.provenance.mapping.view_ids
    assert first.provenance.mapping.seq_ids == second.provenance.mapping.seq_ids == ["1"]
    assert first.provenance.mapping.confidence == second.provenance.mapping.confidence == 0.8
    assert first.provenance.case == second.provenance.case == "split_same_seq"
    assert first.provenance.shared_group == second.provenance.shared_group == "shared_group"
    assert "no_scale" not in first.quality_flags
    assert "no_scale" not in second.quality_flags
    # The second Pair reuses the identical PNG; it is the shared-image copy.
    assert "shared_image" in second.quality_flags
    assert first.status == second.status == "output"
    assert len(writer.images) == 1
    assert writer.images[0][0] == first.image_path
    validate_pair(first)
    validate_pair(second)


def test_l1_without_scale_puts_units_in_review(tmp_path) -> None:
    """R-IMG-09: L1 with no bindable bar is a hard review, no PNG is written."""
    path = line_image(
        tmp_path / "l1_noscale.png",
        boxes=[(30, 30, 90, 90), (160, 30, 220, 90)],
    )
    ocr = ocr_result(
        seqs=[seq_label("1", (40, 40, 50, 50)), seq_label("2", (170, 40, 180, 50))],
    )
    fig = figure(
        path,
        caption="图三 出土器物",
        note="1. 陶豆（M4:1） 2. 陶壶（M4:2）",
        body=[
            para("p1", "陶豆标本M4:1，泥质灰陶。"),
            para("p2", "陶壶标本M4:2，夹砂灰陶。"),
        ],
    )
    writer = FakeWriter()

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(ocr), writer=writer))

    assert result.status == "pending_review"
    assert result.alarms == ["E007"]
    assert result.artifact_map is not None
    assert len(result.artifact_map.units) == 2
    assert all(unit.status == "review" for unit in result.artifact_map.units)
    assert all(unit.scale_bindings == [] for unit in result.artifact_map.units)
    assert any(
        conflict.startswith("group_no_scale:")
        for conflict in result.artifact_map.conflicts
    )
    assert len(result.pairs) == 2
    assert all(pair.status == "review" for pair in result.pairs)
    assert all("no_scale" in pair.quality_flags for pair in result.pairs)
    # A hard alarm forbids emitting a finished PNG (contracts/alarms.md).
    assert writer.images == []


def test_l1_auxiliary_scale_and_seq_glyph_views_are_filtered(tmp_path) -> None:
    """Scale-bar and printed-number glyph views must never become artifact views."""
    path = line_image(
        tmp_path / "l1_aux.png",
        size=(320, 200),
        boxes=[(100, 20, 180, 90), (230, 20, 300, 90)],
        glyphs=[(55, 30, 73, 48), (192, 30, 210, 48)],
        bar=(40, 180, 300, 184),
    )
    raw_views = segment_views(str(path))
    assert len(raw_views) == 5  # two drawings + two glyphs + one scale bar

    ocr = ocr_result(
        seqs=[
            seq_label("1", (50, 28, 150, 50)),
            seq_label("2", (190, 28, 270, 50)),
        ],
        scales=[
            scale_bar(
                "0 5厘米",
                (35, 175, 305, 190),
                prefix_nos=["1", "2"],
                value=5.0,
                unit="厘米",
            )
        ],
    )
    fig = figure(
        path,
        caption="图四 出土器物",
        note="1. 陶豆（M4:1） 2. 陶壶（M4:2）",
        body=[
            para("p1", "陶豆标本M4:1，泥质灰陶。"),
            para("p2", "陶壶标本M4:2，夹砂灰陶。"),
        ],
    )
    writer = FakeWriter()

    results = process_book([fig], PipelineConfig(ocr=FakeOCR(ocr), writer=writer))
    result = results[0]

    assert result.status == "output"
    assert len(result.pairs) == 2
    assert result.artifact_map is not None
    assert [unit.view_ids for unit in result.artifact_map.units] == [[0], [1]]
    assert len(writer.images) == 2

    view_entries = [row for row in writer.ledger if row.get("kind") == "views"]
    assert len(view_entries) == 1
    filtered = view_entries[0]["payload"]
    assert len(filtered) == 2  # three auxiliary views were removed
    aux = [
        (35, 175, 305, 190),
        (50, 28, 150, 50),
        (190, 28, 270, 50),
    ]

    def inside(inner, outer) -> bool:
        return (
            inner[0] >= outer[0]
            and inner[1] >= outer[1]
            and inner[2] <= outer[2]
            and inner[3] <= outer[3]
        )

    assert all(
        not any(inside(tuple(view["bbox"]), bbox) for bbox in aux)
        for view in filtered
    )


def test_l1_without_body_text_marks_no_text_review(tmp_path) -> None:
    """R-OUT-04: no body description still emits Pairs but flags ``no_text``."""
    fig, ocr = _two_artifacts_with_shared_scale(tmp_path)
    fig = fig.model_copy(update={"body_paras": []})
    writer = FakeWriter()

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(ocr), writer=writer))

    assert result.status == "pending_review"
    assert result.alarms == []
    assert len(result.pairs) == 2
    for pair in result.pairs:
        assert pair.description_text is None
        assert pair.text_length == 0
        assert "no_text" in pair.quality_flags
        assert pair.status == "review"
        assert pair.provenance.source_para_ids == []


def test_l1_no_artifact_views_is_pending_review(tmp_path) -> None:
    """A blank canvas yields no views: the declared seqs are reported, not guessed."""
    path = blank_image(tmp_path / "l1_blank.png")
    ocr = ocr_result(
        seqs=[seq_label("1", (10, 10, 20, 20)), seq_label("2", (30, 30, 40, 40))],
    )
    fig = figure(
        path,
        caption="图五 出土器物",
        note="1. 陶豆（M4:1） 2. 陶壶（M4:2）",
        body=[
            para("p1", "陶豆标本M4:1，泥质灰陶。"),
            para("p2", "陶壶标本M4:2，夹砂灰陶。"),
        ],
    )
    writer = FakeWriter()

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(ocr), writer=writer))

    assert result.status == "pending_review"
    assert result.image_type is ImageType.MULTI_LINE
    assert result.pairs == []
    assert result.artifact_map is not None
    assert result.artifact_map.units == []
    assert "E001" in result.alarms
    assert len(result.artifact_map.unbound_seqs) == 2
    assert all(
        item["reason"] == "no_view" for item in result.artifact_map.unbound_seqs
    )
    assert writer.images == []
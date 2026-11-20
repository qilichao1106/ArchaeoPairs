"""T-012 frozen acceptance: glyph-grid seq reading and duplicate sanitising.

Covers card behaviours 1 and 2: small-component filtering/merging, the optional
``read_glyphs`` contract (replace whole-image seqs on success, fall back on
failure), the resulting glyph-view filtering, and ``_sanitize_seq_labels``.
All providers are fakes; no model or network is touched.
"""

from __future__ import annotations

from archaeopairs.models import OcrResult, SeqLabel
from archaeopairs.ocr.vlm import VlmOCRProvider, build_glyph_grid
from archaeopairs.pipeline import (
    PipelineConfig,
    _glyph_candidate_boxes,
    _read_glyph_labels,
    _sanitize_seq_labels,
    process_book,
)
from archaeopairs.vision import segment_views

from t012_synthetic import (
    FakeOCR,
    FakeWriter,
    PlainOCR,
    fake_client,
    figure,
    line_image,
    ocr_result,
    para,
    scale_bar,
    seq_label,
    stage_payload,
    text_block,
    view,
)


def _glyph_figure(tmp_path):
    """Two numbered drawings, two printed glyphs and one shared scale bar."""
    path = line_image(
        tmp_path / "glyph_pipeline.png",
        size=(320, 200),
        boxes=[(100, 20, 180, 90), (230, 20, 300, 90)],
        glyphs=[(55, 30, 73, 48), (192, 30, 210, 48)],
        bar=(40, 180, 300, 183),
    )
    raw = segment_views(str(path))
    glyphs = [v for v in raw if v.bbox[2] - v.bbox[0] <= 60
              and v.bbox[3] - v.bbox[1] <= 60]
    drawings = [v for v in raw if v.bbox[3] - v.bbox[1] > 30]
    fig = figure(
        path,
        caption="图一 出土器物",
        note="1. 陶鼎（M1:1） 2. 陶盒（M1:2）",
        body=[
            para("p1", "陶鼎标本M1:1，泥质灰陶。"),
            para("p2", "陶盒标本M1:2，泥质灰陶。"),
        ],
    )
    return str(path), glyphs, drawings, fig


def _scale():
    return scale_bar("0 4厘米", (35, 175, 305, 190), prefix_nos=["1", "2"])


def test_glyph_candidate_boxes_filter_size_text_scale_and_legend() -> None:
    views = [
        view(0, (10, 10, 20, 20)),        # top 3% legend band
        view(1, (30, 100, 33, 120)),      # too narrow
        view(2, (40, 100, 110, 120)),     # too wide
        view(3, (50, 100, 54, 103)),      # too short
        view(4, (100, 100, 110, 120)),    # plain digit
        view(5, (210, 110, 220, 130)),    # centre inside a short text line
        view(6, (310, 110, 320, 130)),    # centre inside a scale box
        view(7, (520, 100, 530, 120)),    # inside a >60px-tall text block
    ]
    ocr = ocr_result(
        texts=[
            text_block("1", (200, 100, 260, 140)),
            text_block("tall", (500, 50, 600, 300)),
        ],
        scales=[scale_bar("0 4厘米", (300, 100, 400, 140))],
    )

    boxes = _glyph_candidate_boxes(views, ocr, (1000, 1000))

    # Reading order; the tall text block does not exclude its digit.
    assert boxes == [(100, 100, 110, 120), (520, 100, 530, 120)]
    assert _glyph_candidate_boxes(views, ocr, None) == []


def test_glyph_candidate_boxes_merge_multi_digit_run_only() -> None:
    merged = _glyph_candidate_boxes(
        [view(0, (700, 100, 710, 120)), view(1, (716, 100, 726, 120)),
         view(2, (740, 100, 750, 120))],
        ocr_result(),
        (1000, 1000),
    )
    assert merged == [(700, 100, 726, 120), (740, 100, 750, 120)]

    apart = _glyph_candidate_boxes(
        [view(0, (100, 200, 110, 220)), view(1, (117, 200, 127, 220))],
        ocr_result(),
        (1000, 1000),
    )
    assert apart == [(100, 200, 110, 220), (117, 200, 127, 220)]


def test_read_glyph_labels_normalizes_and_skips_unreadable_cells() -> None:
    boxes = [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12)]
    provider = FakeOCR(glyphs=["1", None, "A"])

    labels = _read_glyph_labels(provider, "glyphs.png", boxes)

    assert [label.text for label in labels] == ["1", "A"]
    assert [tuple(label.bbox) for label in labels] == [boxes[0], boxes[2]]
    assert all(label.conf == 0.9 for label in labels)
    assert provider.glyph_calls == [("glyphs.png", boxes)]


def test_read_glyph_labels_requires_a_capable_provider() -> None:
    boxes = [(1, 2, 3, 4)]
    assert _read_glyph_labels(PlainOCR(OcrResult()), "x.png", boxes) == []


def test_read_glyph_labels_swallows_errors_and_length_mismatch() -> None:
    boxes = [(1, 2, 3, 4), (5, 6, 7, 8)]
    assert _read_glyph_labels(
        FakeOCR(glyph_error=RuntimeError("vlm down")), "x.png", boxes
    ) == []
    assert _read_glyph_labels(FakeOCR(glyphs=["1"]), "x.png", boxes) == []
    assert _read_glyph_labels(FakeOCR(glyphs=["1", "2"]), "x.png", []) == []


def test_vlm_glyph_grid_reader_is_offline_and_ordered(tmp_path) -> None:
    path = line_image(
        tmp_path / "glyph_grid.png",
        size=(200, 120),
        glyphs=[(20, 20, 30, 40), (50, 20, 60, 40), (80, 20, 90, 40)],
    )
    boxes = [(20, 20, 30, 40), (50, 20, 60, 40), (80, 20, 90, 40)]
    client = fake_client('{"glyphs": ["1", null, "A"]}')

    provider = VlmOCRProvider(client)
    assert provider.read_glyphs(path, boxes) == ["1", None, "A"]
    assert len(client.calls) == 1
    assert client.calls[0][2] is True
    assert "共 3 个格子" in client.calls[0][1]

    grid = build_glyph_grid(path, boxes + [(110, 20, 120, 40), (140, 20, 150, 40)])
    assert grid.mode == "RGB"
    assert grid.size == (4 * 128, 2 * 128)  # four cells per row, five boxes


def test_pipeline_glyph_labels_replace_ocr_seqs_and_drop_glyph_views(tmp_path) -> None:
    path, glyph_views, drawings, fig = _glyph_figure(tmp_path)
    assert len(glyph_views) == 2 and len(drawings) == 2
    ocr = FakeOCR(
        ocr_result(seqs=[seq_label("9", (5, 5, 15, 15))], scales=[_scale()]),
        glyphs=["1", "2"],
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=ocr, writer=writer))[0]

    assert result.status == "output"
    assert [pair.provenance.mapping.seq_ids for pair in result.pairs] == [["1"], ["2"]]
    assert all("9" not in pair.provenance.mapping.seq_ids for pair in result.pairs)

    assert len(ocr.glyph_calls) == 1
    called_path, called_boxes = ocr.glyph_calls[0]
    assert called_path == path
    assert called_boxes == [tuple(v.bbox) for v in glyph_views]

    views_payload = stage_payload(writer.ledger, "views")
    assert [tuple(item["bbox"]) for item in views_payload] == [
        tuple(v.bbox) for v in drawings
    ]
    assert not any(
        tuple(item["bbox"]) == tuple(v.bbox)
        for item in views_payload for v in glyph_views
    )

    ocr_payload = stage_payload(writer.ledger, "ocr")
    assert [item["text"] for item in ocr_payload["seqs"]] == ["1", "2"]
    assert [tuple(item["bbox"]) for item in ocr_payload["seqs"]] == called_boxes


def test_pipeline_falls_back_to_whole_image_seqs_without_glyph_reader(tmp_path) -> None:
    _path, glyph_views, _drawings, fig = _glyph_figure(tmp_path)
    provider = PlainOCR(ocr_result(
        seqs=[seq_label("1", (50, 28, 150, 50)),
              seq_label("2", (190, 28, 270, 50))],
        scales=[_scale()],
    ))
    writer = FakeWriter()
    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    assert result.status == "output"
    assert [pair.provenance.mapping.seq_ids for pair in result.pairs] == [["1"], ["2"]]
    views_payload = stage_payload(writer.ledger, "views")
    assert len(views_payload) == 2
    assert not any(
        tuple(item["bbox"]) == tuple(v.bbox)
        for item in views_payload for v in glyph_views
    )


def test_sanitize_keeps_only_duplicate_near_its_glyph() -> None:
    views = [view(0, (100, 100, 110, 120)), view(1, (300, 50, 500, 400))]
    near_glyph = SeqLabel(text="1", bbox=(112, 100, 122, 120), conf=0.99)
    inside_drawing = SeqLabel(text="1", bbox=(400, 200, 410, 220), conf=0.99)

    kept = _sanitize_seq_labels([near_glyph, inside_drawing], views)

    assert kept == [near_glyph]


def test_sanitize_keeps_duplicates_that_each_sit_on_a_glyph() -> None:
    views = [view(0, (100, 100, 110, 120)), view(1, (300, 100, 310, 120))]
    first = SeqLabel(text="1", bbox=(112, 100, 122, 120), conf=0.99)
    second = SeqLabel(text="①", bbox=(312, 100, 322, 120), conf=0.99)

    assert _sanitize_seq_labels([first, second], views) == [first, second]


def test_sanitize_without_glyph_reference_keeps_smallest_box() -> None:
    views = [view(0, (300, 50, 500, 400))]
    large = SeqLabel(text="1", bbox=(100, 100, 140, 140), conf=0.99)
    small = SeqLabel(text="1", bbox=(200, 200, 210, 220), conf=0.99)
    passthrough = SeqLabel(text="2、3", bbox=(600, 600, 700, 700), conf=0.99)

    kept = _sanitize_seq_labels([large, small, passthrough], views)

    assert kept == [passthrough, small]
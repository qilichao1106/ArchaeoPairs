"""T-012 frozen acceptance: text blocks may not swallow drawings.

Card behaviour 3: ``_text_owned`` only claims a large view when at least 75%
of it is covered, so a bogus VLM text block (a whole vessel read as ``"I"``)
leaves the drawing untouched; glyph-sized views keep the ``_aux_owned``
semantics and are still removed by a text line that covers them.
"""

from __future__ import annotations

from archaeopairs.pipeline import (
    PipelineConfig,
    _filter_aux_views,
    _text_owned,
    process_book,
)
from archaeopairs.vision import segment_views

from t012_synthetic import (
    FakeOCR,
    FakeWriter,
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

LARGE_VIEW = (100, 100, 300, 300)


def test_large_view_is_retained_when_text_covers_less_than_75_percent() -> None:
    partial = (250, 100, 450, 300)       # 25% overlap
    thin_i = (150, 150, 160, 250)        # bogus text block over the vessel
    outside = (400, 400, 500, 500)

    assert _text_owned(LARGE_VIEW, partial) is False
    assert _text_owned(LARGE_VIEW, thin_i) is False
    assert _text_owned(LARGE_VIEW, outside) is False


def test_large_view_is_text_owned_at_or_above_75_percent() -> None:
    assert _text_owned(LARGE_VIEW, (100, 100, 280, 300)) is True  # 90%
    assert _text_owned(LARGE_VIEW, (50, 50, 350, 350)) is True    # contained


def test_small_glyph_view_covered_by_a_text_line_stays_text_owned() -> None:
    glyph = (100, 100, 110, 115)

    assert _text_owned(glyph, (80, 90, 200, 120)) is True
    assert _text_owned(glyph, (300, 300, 400, 400)) is False


def test_filter_aux_views_keeps_drawing_under_a_thin_text_block() -> None:
    views = [view(0, (100, 20, 260, 160)), view(1, (55, 30, 73, 48))]
    ocr = ocr_result(texts=[text_block("I", (150, 40, 160, 140)),
                            text_block("1", (50, 25, 80, 55))])

    filtered = _filter_aux_views(views, ocr)

    assert [tuple(item.bbox) for item in filtered] == [(100, 20, 260, 160)]
    assert [item.view_id for item in filtered] == [0]


def test_pipeline_emits_drawing_that_vlm_mislabels_as_text(tmp_path) -> None:
    path = line_image(
        tmp_path / "text_i.png",
        size=(400, 220),
        boxes=[(100, 20, 260, 160), (300, 20, 380, 160)],
        glyphs=[(55, 30, 73, 48)],
        bar=(20, 190, 380, 193),
    )
    raw = segment_views(str(path))
    glyph_views = [v for v in raw if v.bbox[2] - v.bbox[0] <= 60
                   and v.bbox[3] - v.bbox[1] <= 60]
    drawings = [v for v in raw if v.bbox[3] - v.bbox[1] > 30]
    assert len(glyph_views) == 1 and len(drawings) == 2

    ocr = FakeOCR(ocr_result(
        seqs=[seq_label("1", (110, 30, 120, 45)),
              seq_label("2", (310, 30, 320, 45))],
        texts=[text_block("I", (150, 40, 160, 140)),
               text_block("1", (50, 25, 80, 55))],
        scales=[scale_bar("0 4厘米", (15, 185, 385, 205), prefix_nos=["1", "2"])],
    ))
    fig = figure(
        path,
        caption="图一 出土器物",
        note="1. 陶鼎（M1:1） 2. 陶盒（M1:2）",
        body=[para("p1", "陶鼎标本M1:1，泥质灰陶。"),
              para("p2", "陶盒标本M1:2，泥质灰陶。")],
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=ocr, writer=writer))[0]

    assert result.status == "output"
    assert len(result.pairs) == 2
    assert all(pair.provenance.mapping.view_ids for pair in result.pairs)
    payload = stage_payload(writer.ledger, "views")
    assert [tuple(item["bbox"]) for item in payload] == [
        tuple(item.bbox) for item in drawings
    ]
    assert not any(
        tuple(item["bbox"]) == tuple(glyph.bbox)
        for item in payload for glyph in glyph_views
    )
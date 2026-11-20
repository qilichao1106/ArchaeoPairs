"""T-013 frozen acceptance: glyph-grid fallback and top legend-band filtering.

Covers card behaviours 4-5 with fakes only:

* ``read_glyphs`` returning ``[]`` or raising, on a provider that has
  ``read_scales``, must trigger one full ``read`` for seqs while the first
  scales are retained;
* ``_filter_aux_views`` drops small views centred in the top 3% band, keeps
  drawings wider/taller than 60 px, and without ``image_shape`` keeps the old
  OCR-box-only behaviour.
"""

from __future__ import annotations

from archaeopairs.models import OcrResult
from archaeopairs.pipeline import PipelineConfig, _filter_aux_views, process_book

from t013_synthetic import (
    FakeWriter,
    ScriptedOCR,
    glyph_seq_labels,
    l1_figure,
    ocr_result,
    scale_bar,
    seq_label,
    shared_scale,
    stage_payload,
    text_block,
    view,
)


def _fallback_run(tmp_path, **glyph_kwargs):
    """Run L1 where the glyph grid fails; the full read offers a different bar."""
    path, fig = l1_figure(tmp_path)
    full = ocr_result(
        seqs=glyph_seq_labels(),
        scales=[scale_bar("0 9厘米", (35, 175, 305, 190), prefix_nos=["1", "2"])],
        source="full-read",
    )
    provider = ScriptedOCR(
        scale_results=[ocr_result(scales=[shared_scale()], source="scale-reader")],
        read_result=full,
        **glyph_kwargs,
    )
    writer = FakeWriter()
    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]
    return path, result, writer, provider


def _assert_fallback_kept_scale(result, writer) -> None:
    assert result.status == "output"
    assert [p.provenance.mapping.seq_ids for p in result.pairs] == [["1"], ["2"]]
    assert all(p.provenance.mapping.scale_ids == [0] for p in result.pairs)
    assert all(
        p.provenance.mapping.scale_sources == ["L1_prefix"] for p in result.pairs
    )
    payload = stage_payload(writer.ledger, "ocr")
    assert [item["text"] for item in payload["seqs"]] == ["1", "2"]
    # Scales still come from read_scales, never from the fallback full read.
    assert [item["text"] for item in payload["scales"]] == ["0 4厘米"]
    assert payload["scales"][0]["prefix_nos"] == ["1", "2"]


# ---------------------------------------------------------------------------
# Behaviour 4: empty / failing glyph grid falls back to full read
# ---------------------------------------------------------------------------


def test_empty_glyph_grid_falls_back_to_full_read_for_seqs(tmp_path) -> None:
    path, result, writer, provider = _fallback_run(tmp_path, glyphs=[])

    assert provider.scale_calls == [path]  # scale present -> no retry
    assert provider.read_calls == [path]  # exactly one fallback read
    assert len(provider.glyph_calls) == 1
    _assert_fallback_kept_scale(result, writer)


def test_raising_glyph_grid_falls_back_to_full_read_for_seqs(tmp_path) -> None:
    path, result, writer, provider = _fallback_run(
        tmp_path, glyph_error=RuntimeError("glyph reader down")
    )

    assert provider.scale_calls == [path]
    assert provider.read_calls == [path]
    assert len(provider.glyph_calls) == 1
    _assert_fallback_kept_scale(result, writer)


# ---------------------------------------------------------------------------
# Behaviour 5: top legend-band filtering
# ---------------------------------------------------------------------------


def test_top_band_drops_only_small_views_centred_inside_it() -> None:
    views = [
        view(0, (100, 5, 120, 20)),     # centre 12.5 -> dropped
        view(1, (100, 26, 120, 34)),    # centre exactly 30 -> kept
        view(2, (100, 0, 161, 20)),     # width 61 -> kept
        view(3, (100, 0, 140, 70)),     # height 70 -> kept
        view(4, (300, 500, 500, 700)),  # ordinary drawing -> kept
    ]

    kept = _filter_aux_views(views, OcrResult(), (1000, 1000))

    assert [tuple(item.bbox) for item in kept] == [
        (100, 26, 120, 34),
        (100, 0, 161, 20),
        (100, 0, 140, 70),
        (300, 500, 500, 700),
    ]
    assert [item.view_id for item in kept] == [0, 1, 2, 3]


def test_without_image_shape_keeps_top_band_but_still_filters_ocr_boxes() -> None:
    ocr = ocr_result(
        scales=[scale_bar("0 4厘米", (295, 495, 385, 515))],
        texts=[text_block("器物", (390, 590, 430, 630))],
        seqs=[seq_label("1", (500, 700, 510, 720))],
    )
    views = [
        view(0, (100, 5, 120, 20)),      # top legend: no shape -> kept
        view(1, (300, 500, 380, 506)),   # inside the scale box -> dropped
        view(2, (400, 600, 420, 620)),   # inside the text block -> dropped
        view(3, (505, 700, 515, 720)),   # the printed seq glyph -> dropped
        view(4, (600, 600, 700, 700)),   # drawing -> kept
    ]

    kept = _filter_aux_views(views, ocr)

    assert [tuple(item.bbox) for item in kept] == [
        (100, 5, 120, 20),
        (600, 600, 700, 700),
    ]
    assert [item.view_id for item in kept] == [0, 1]


def test_with_image_shape_filters_legend_and_ocr_owned_views() -> None:
    ocr = ocr_result(
        scales=[scale_bar("0 4厘米", (295, 495, 385, 515))],
        texts=[text_block("器物", (390, 590, 430, 630))],
        seqs=[seq_label("1", (500, 700, 510, 720))],
    )
    views = [
        view(7, (100, 5, 120, 20)),      # top legend -> dropped
        view(8, (300, 500, 380, 506)),   # scale-owned -> dropped
        view(9, (400, 600, 420, 620)),   # text-owned -> dropped
        view(10, (505, 700, 515, 720)),  # seq-glyph-owned -> dropped
        view(11, (600, 600, 700, 700)),  # drawing -> kept
    ]

    kept = _filter_aux_views(views, ocr, (1000, 1000))

    assert [tuple(item.bbox) for item in kept] == [(600, 600, 700, 700)]
    assert [item.view_id for item in kept] == [0]
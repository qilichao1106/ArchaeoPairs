"""T-013 frozen acceptance: scales-only OCR priority and scale-miss retry.

Covers card behaviours 1-3 with fake providers only:

* a provider exposing both ``read_scales`` and ``read`` must be read through
  ``read_scales`` (full ``read`` is never called when the glyph grid succeeds);
* ``ocr_result.seqs`` comes from ``read_glyphs``, ``scales``/``texts`` from
  ``read_scales``;
* a provider with only ``read`` falls back exactly like T-010;
* a first empty scale read is retried once, two empties stop at two calls and
  degrade to the no-scale review path, a first hit is never retried.
"""

from __future__ import annotations

from archaeopairs.pipeline import PipelineConfig, process_book

from t013_synthetic import (
    FakeWriter,
    PlainOCR,
    ScriptedOCR,
    glyph_seq_labels,
    l1_figure,
    ocr_result,
    seq_label,
    shared_scale,
    stage_payload,
    text_block,
)

_SCALE_TEXT = text_block("比例尺", (200, 180, 260, 190))


def _scale_reader_result():
    """A scales-only reply: one bar plus a text line, no usable seqs."""
    return ocr_result(
        seqs=[seq_label("9", (5, 5, 15, 15))],
        scales=[shared_scale()],
        texts=[_SCALE_TEXT],
        source="scale-reader",
    )


# ---------------------------------------------------------------------------
# Behaviour 1: scales-only priority
# ---------------------------------------------------------------------------


def test_l1_uses_read_scales_and_never_full_read(tmp_path) -> None:
    path, fig = l1_figure(tmp_path)
    full = ocr_result(
        seqs=[seq_label("8", (5, 5, 15, 15))],
        scales=[shared_scale(text="0 9厘米")],
        source="full-read",
    )
    provider = ScriptedOCR(
        scale_results=[_scale_reader_result()], glyphs=["1", "2"], read_result=full
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    assert provider.scale_calls == [path]
    assert provider.read_calls == []
    assert len(provider.glyph_calls) == 1
    assert provider.glyph_calls[0][0] == path
    assert result.status == "output"
    assert [p.artifact_id for p in result.pairs] == ["M1:1", "M1:2"]


def test_l1_merges_glyph_seqs_with_scale_reader_scales_and_texts(tmp_path) -> None:
    _path, fig = l1_figure(tmp_path)
    provider = ScriptedOCR(
        scale_results=[_scale_reader_result()], glyphs=["1", "2"]
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    payload = stage_payload(writer.ledger, "ocr")
    # Seqs are the glyph-grid labels (bbox = the candidate boxes handed over).
    assert [item["text"] for item in payload["seqs"]] == ["1", "2"]
    assert [tuple(item["bbox"]) for item in payload["seqs"]] == (
        provider.glyph_calls[0][1]
    )
    # Scales/texts come from read_scales, never from the full read.
    assert [item["text"] for item in payload["scales"]] == ["0 4厘米"]
    assert payload["scales"][0]["prefix_nos"] == ["1", "2"]
    assert payload["texts"] == [_SCALE_TEXT.model_dump()]

    assert [p.provenance.mapping.seq_ids for p in result.pairs] == [["1"], ["2"]]
    assert [tuple(p.provenance.mapping.view_ids) for p in result.pairs] == [
        (0,),
        (1,),
    ]
    assert all(p.provenance.mapping.scale_ids == [0] for p in result.pairs)
    assert all(
        p.provenance.mapping.scale_sources == ["L1_prefix"] for p in result.pairs
    )


# ---------------------------------------------------------------------------
# Behaviour 2: provider without read_scales
# ---------------------------------------------------------------------------


def test_provider_without_read_scales_falls_back_to_full_read(tmp_path) -> None:
    path, fig = l1_figure(tmp_path)
    full = ocr_result(
        seqs=glyph_seq_labels(),
        scales=[shared_scale()],
        texts=[_SCALE_TEXT],
        source="paddle",
    )
    provider = PlainOCR(full)
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    assert provider.read_calls == [path]  # exactly one whole-image read
    assert not hasattr(provider, "read_scales")
    assert result.status == "output"
    assert result.alarms == []
    assert [p.artifact_id for p in result.pairs] == ["M1:1", "M1:2"]
    payload = stage_payload(writer.ledger, "ocr")
    assert [item["text"] for item in payload["seqs"]] == ["1", "2"]
    assert [item["text"] for item in payload["scales"]] == ["0 4厘米"]


def test_provider_without_read_scales_keeps_t010_pair_contract(tmp_path) -> None:
    _path, fig = l1_figure(tmp_path)
    provider = PlainOCR(
        ocr_result(
            seqs=glyph_seq_labels(),
            scales=[shared_scale()],
            source="paddle",
        )
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    assert result.status == "output"
    assert [p.image_path for p in result.pairs] == [
        "图一_1_M1-1.png",
        "图一_2_M1-2.png",
    ]
    assert [p.provenance.mapping.seq_ids for p in result.pairs] == [["1"], ["2"]]
    assert [tuple(p.provenance.mapping.view_ids) for p in result.pairs] == [
        (0,),
        (1,),
    ]
    assert all(p.provenance.mapping.scale_sources == ["L1_prefix"] for p in result.pairs)
    assert [name for name, _shape in writer.images] == [
        p.image_path for p in result.pairs
    ]


# ---------------------------------------------------------------------------
# Behaviour 3: scale-miss retry (exactly once)
# ---------------------------------------------------------------------------


def test_retry_once_when_first_scale_read_misses(tmp_path) -> None:
    path, fig = l1_figure(tmp_path)
    second = ocr_result(
        scales=[shared_scale()], texts=[_SCALE_TEXT], source="second-pass"
    )
    provider = ScriptedOCR(
        scale_results=[ocr_result(source="first-pass"), second], glyphs=["1", "2"]
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    assert provider.scale_calls == [path, path]
    assert provider.read_calls == []
    assert result.status == "output"
    payload = stage_payload(writer.ledger, "ocr")
    assert [item["text"] for item in payload["scales"]] == ["0 4厘米"]
    assert payload["texts"] == [_SCALE_TEXT.model_dump()]
    assert all(p.provenance.mapping.scale_ids == [0] for p in result.pairs)


def test_two_empty_scale_reads_stop_after_two_attempts(tmp_path) -> None:
    path, fig = l1_figure(tmp_path)
    provider = ScriptedOCR(
        scale_results=[ocr_result(source="first"), ocr_result(source="second")],
        glyphs=["1", "2"],
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    # The scripted list is exhausted after two; a third call would raise.
    assert provider.scale_calls == [path, path]
    assert provider.scale_results == []
    assert provider.read_calls == []
    assert result.status == "pending_review"
    assert result.alarms == ["E007"]
    assert len(result.pairs) == 2
    assert all(pair.status == "review" for pair in result.pairs)
    assert all("no_scale" in pair.quality_flags for pair in result.pairs)
    assert any(
        conflict.startswith("group_no_scale:")
        for conflict in result.artifact_map.conflicts
    )
    assert writer.images == []


def test_existing_scale_is_not_retried(tmp_path) -> None:
    path, fig = l1_figure(tmp_path)
    provider = ScriptedOCR(
        scale_results=[_scale_reader_result()], glyphs=["1", "2"]
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=provider, writer=writer))[0]

    # Only the first scripted result exists: any retry would raise.
    assert provider.scale_calls == [path]
    assert provider.scale_results == []
    assert result.status == "output"
    assert all(p.provenance.mapping.scale_ids == [0] for p in result.pairs)
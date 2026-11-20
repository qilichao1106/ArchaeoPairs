"""T-010 frozen acceptance: L2/L3 whole-image passthrough and L4 archive.

L2/L3 must not segment or OCR; one unique artifact is emitted as the whole image
with the ``01`` seq segment and ``no_scale``.  L4 must never touch OCR/writer and
must emit zero Pairs with an explicit exclusion reason (R-L4-01/02).
"""

from __future__ import annotations

import pytest

from archaeopairs.models import ImageType, WorkLine
from archaeopairs.pipeline import PipelineConfig, process_figure

from t010_synthetic import (
    FakeOCR,
    FakeWriter,
    color_image,
    figure,
    line_image,
    para,
    validate_pair,
)


def test_l2_single_line_whole_image(tmp_path) -> None:
    path = line_image(
        tmp_path / "l2.png", size=(160, 120), boxes=[(30, 20, 90, 80)]
    )
    writer = FakeWriter()
    ocr = FakeOCR(error=AssertionError("L2 must not call OCR"))
    fig = figure(
        path,
        caption="图2-1-5 铜鼎（M4:6）",
        body=[para("p1", "铜鼎标本M4:6，通高10厘米。")],
    )

    result = process_figure(fig, PipelineConfig(ocr=ocr, writer=writer))

    assert ocr.calls == []  # R-L2: no segmentation/OCR on the whole-image path
    assert result.status == "output"
    assert result.image_type is ImageType.SINGLE_LINE
    assert result.work_line is WorkLine.SINGLE_LINE
    assert result.artifact_map is None
    assert len(result.pairs) == 1

    pair = result.pairs[0]
    assert pair.artifact_id == "M4:6"
    assert pair.figure_number == "图2-1-5"
    assert pair.source_role == "line"
    assert pair.image_merge_mode == "line_only"
    assert pair.image_path == "图2-1-5_01_M4-6.png"
    assert pair.status == "output"
    assert pair.quality_flags == ["no_scale"]
    assert pair.description_text == "铜鼎标本M4:6，通高10厘米。"
    assert pair.text_length == len(pair.description_text)

    mapping = pair.provenance.mapping
    assert mapping.artifact_id == "M4:6"
    assert mapping.seq_ids == []
    assert mapping.view_ids == []
    assert mapping.scale_ids == []
    assert mapping.scale_sources == []
    assert mapping.confidence == 1.0
    assert mapping.line == WorkLine.SINGLE_LINE
    assert mapping.source_role == "line"
    assert pair.provenance.art_source == "caption"
    assert pair.provenance.case == "single_line_artifact"
    assert pair.provenance.source_para_ids == ["p1"]
    validate_pair(pair)

    # One PNG: the original pixels plus the 6 px minimum white margin.
    assert len(writer.images) == 1
    name, shape = writer.images[0]
    assert name == pair.image_path
    assert shape == (132, 172, 3)


def test_l3_single_plate_whole_image(tmp_path) -> None:
    path = color_image(tmp_path / "l3.png", size=(160, 120))
    writer = FakeWriter()
    ocr = FakeOCR(error=AssertionError("L3 must not call OCR"))
    fig = figure(
        path,
        caption="图版204",
        note="1. 陶罐（M4:1）",
        body=[para("p1", "陶罐标本M4:1，泥质灰陶。")],
    )

    result = process_figure(fig, PipelineConfig(ocr=ocr, writer=writer))

    assert ocr.calls == []
    assert result.status == "output"
    assert result.image_type is ImageType.SINGLE_PLATE
    assert result.work_line is WorkLine.SINGLE_PLATE
    assert result.artifact_map is None
    assert len(result.pairs) == 1

    pair = result.pairs[0]
    assert pair.artifact_id == "M4:1"
    assert pair.figure_number == "图版204"
    assert pair.source_role == "plate"
    assert pair.image_merge_mode == "plate_only"
    assert pair.image_path == "图版204_01_M4-1.png"
    assert pair.status == "output"
    assert pair.quality_flags == ["no_scale"]
    assert pair.description_text == "陶罐标本M4:1，泥质灰陶。"

    mapping = pair.provenance.mapping
    assert mapping.seq_ids == []
    assert mapping.view_ids == []
    assert mapping.scale_ids == []
    assert mapping.confidence == 1.0
    assert mapping.line == WorkLine.SINGLE_PLATE
    assert mapping.source_role == "plate"
    assert pair.provenance.art_source == "figure_note"
    assert pair.provenance.case == "single_plate_artifact"
    validate_pair(pair)

    assert len(writer.images) == 1
    assert writer.images[0][0] == pair.image_path
    assert writer.images[0][1] == (132, 172, 3)


@pytest.mark.parametrize(
    ("kind", "caption", "note", "expected_type", "reason"),
    [
        (
            "multi_plate",
            "图版一 陶罐、陶壶",
            "1. 陶罐（M4:1） 2. 陶壶（M4:2）",
            ImageType.MULTI_PLATE,
            "multi_plate_artifact",
        ),
        (
            "discarded",
            "图一 纹饰",
            "0 8厘米",
            ImageType.DISCARDED,
            "discarded",
        ),
    ],
)
def test_l4_archives_without_ocr_or_compose(
    tmp_path, kind, caption, note, expected_type, reason
) -> None:
    path = (
        color_image(tmp_path / f"{kind}.png")
        if kind == "multi_plate"
        else line_image(tmp_path / f"{kind}.png", boxes=[(30, 30, 90, 90)])
    )
    writer = FakeWriter()
    ocr = FakeOCR(error=AssertionError("L4 must not call OCR"))
    fig = figure(path, caption=caption, note=note)

    result = process_figure(fig, PipelineConfig(ocr=ocr, writer=writer))

    assert ocr.calls == []
    assert writer.images == []
    assert writer.pairs == []
    assert result.status == "excluded"
    assert result.image_type is expected_type
    assert result.work_line is WorkLine.ARCHIVE
    assert result.pairs == []
    assert result.artifact_map is None
    assert result.exclude_reason == reason
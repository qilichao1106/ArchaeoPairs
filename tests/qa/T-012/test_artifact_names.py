"""T-012 frozen acceptance: artifact names from the figure note.

Card behaviour 6: L1 fills ``PairRecord.artifact_name`` from the note clause
that owns each seq; L2/L3 fill it when the unique artifact id appears in a
named note item, and keep ``None`` when no name is printed.
"""

from __future__ import annotations

from archaeopairs.models import ImageType, WorkLine
from archaeopairs.pipeline import PipelineConfig, process_figure

from t012_synthetic import (
    FakeOCR,
    FakeWriter,
    color_image,
    figure,
    line_image,
    ocr_result,
    para,
    scale_bar,
    seq_label,
)


def test_l1_note_names_are_written_to_pair_records(tmp_path) -> None:
    path = line_image(
        tmp_path / "l1_names.png",
        boxes=[(30, 30, 90, 90), (160, 30, 220, 90)],
        bar=(20, 160, 280, 164),
    )
    ocr = FakeOCR(ocr_result(
        seqs=[seq_label("1", (40, 40, 50, 50)),
              seq_label("2", (170, 40, 180, 50))],
        scales=[scale_bar("0 4厘米", (15, 155, 285, 175), prefix_nos=["1", "2"])],
    ))
    fig = figure(
        path,
        caption="图一 出土器物",
        note="1. 陶鼎（M1:1） 2. 陶盒（M1:2）",
        body=[para("p1", "陶鼎标本M1:1，泥质灰陶。"),
              para("p2", "陶盒标本M1:2，泥质灰陶。")],
    )

    result = process_figure(fig, PipelineConfig(ocr=ocr, writer=FakeWriter()))

    assert result.status == "output"
    assert [(pair.artifact_id, pair.artifact_name) for pair in result.pairs] == [
        ("M1:1", "陶鼎"),
        ("M1:2", "陶盒"),
    ]


def test_l2_note_name_is_written_when_the_unique_id_matches(tmp_path) -> None:
    path = line_image(
        tmp_path / "l2_name.png", size=(160, 120), boxes=[(30, 20, 90, 80)]
    )
    fig = figure(
        path,
        caption="图2-1-5 铜鼎（M4:6）",
        note="1. 铜鼎（M4:6）",
        body=[para("p1", "铜鼎标本M4:6，通高10厘米。")],
    )

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(), writer=FakeWriter()))

    assert result.image_type is ImageType.SINGLE_LINE
    assert result.work_line is WorkLine.SINGLE_LINE
    assert result.status == "output"
    assert len(result.pairs) == 1
    assert result.pairs[0].artifact_id == "M4:6"
    assert result.pairs[0].artifact_name == "铜鼎"


def test_l3_note_name_is_written_when_the_unique_id_matches(tmp_path) -> None:
    path = color_image(tmp_path / "l3_name.png")
    fig = figure(
        path,
        caption="图版204",
        note="1. 陶罐（M4:1）",
        body=[para("p1", "陶罐标本M4:1，泥质灰陶。")],
    )

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(), writer=FakeWriter()))

    assert result.image_type is ImageType.SINGLE_PLATE
    assert result.work_line is WorkLine.SINGLE_PLATE
    assert result.status == "output"
    assert result.pairs[0].artifact_name == "陶罐"


def test_l2_without_a_named_note_keeps_artifact_name_none(tmp_path) -> None:
    path = line_image(
        tmp_path / "l2_unnamed.png", size=(160, 120), boxes=[(30, 20, 90, 80)]
    )
    fig = figure(
        path,
        caption="图2-1-6 铜鼎（M4:7）",
        body=[para("p1", "铜鼎标本M4:7，通高12厘米。")],
    )

    result = process_figure(fig, PipelineConfig(ocr=FakeOCR(), writer=FakeWriter()))

    assert result.status == "output"
    assert result.pairs[0].artifact_id == "M4:7"
    assert result.pairs[0].artifact_name is None
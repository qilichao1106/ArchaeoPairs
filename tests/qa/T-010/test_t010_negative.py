"""T-010 frozen negative controls: real injected failures must fail closed.

Each test injects a genuine fault and asserts the pipeline either records it on
the FigureResult or turns it into ``pending_review``/``failed`` -- never a
guessed Pair or a silently empty success:

* OCR provider raises;
* the media file is not a readable image;
* the canvas has no view at all (E001 evidence);
* the Writer raises while persisting the PNG;
* a single-artifact figure resolves no artifact id (E005);
* a single-artifact route is handed more than one artifact id (E005).
"""

from __future__ import annotations

from archaeopairs.models import ImageType, WorkLine
from archaeopairs.pipeline import PipelineConfig, process_book, process_figure

from t010_synthetic import (
    FakeOCR,
    FakeWriter,
    blank_image,
    figure,
    line_image,
    ocr_result,
    para,
    seq_label,
)


def _multi_line_figure(path):
    return figure(
        path,
        caption="图一 出土器物",
        note="1. 陶豆（M4:1） 2. 陶壶（M4:2）",
        body=[
            para("p1", "陶豆标本M4:1，泥质灰陶。"),
            para("p2", "陶壶标本M4:2，夹砂灰陶。"),
        ],
        figure_id="fig-bad",
    )


def test_negative_ocr_error_is_marked_failed(tmp_path) -> None:
    path = line_image(
        tmp_path / "ocr_raises.png",
        boxes=[(30, 30, 90, 90), (160, 30, 220, 90)],
        bar=(20, 160, 280, 164),
    )
    writer = FakeWriter()
    ocr = FakeOCR(error=RuntimeError("ocr down"))

    results = process_book(
        [_multi_line_figure(path)], PipelineConfig(ocr=ocr, writer=writer)
    )

    assert len(ocr.calls) == 1
    assert results[0].status == "failed"
    assert results[0].conflicts == ["pipeline_failed:RuntimeError"]
    assert results[0].pairs == []
    assert writer.images == []
    assert writer.pairs == []
    # process_book still flushes both book-level sinks for the batch.
    assert writer.write_pairs_calls == 1
    assert writer.write_ledger_calls == 1


def test_negative_unreadable_image_fails_closed(tmp_path) -> None:
    path = tmp_path / "broken.png"
    path.write_bytes(b"this is not a decodable image")
    writer = FakeWriter()
    fig = figure(
        path,
        caption="图2-1-5 铜鼎（M4:6）",
        body=[para("p1", "铜鼎标本M4:6，通高10厘米。")],
    )

    result = process_figure(fig, PipelineConfig(writer=writer))

    assert result.status == "failed"
    assert result.image_type is ImageType.SINGLE_LINE
    assert result.work_line is WorkLine.SINGLE_LINE
    assert result.pairs == []
    assert result.conflicts == ["compose_failed:OSError"]
    assert writer.images == []
    assert writer.pairs == []


def test_negative_empty_views_pend_with_e001(tmp_path) -> None:
    path = blank_image(tmp_path / "no_views.png")
    ocr = ocr_result(
        seqs=[seq_label("1", (10, 10, 20, 20)), seq_label("2", (30, 30, 40, 40))]
    )
    writer = FakeWriter()

    result = process_figure(
        _multi_line_figure(path), PipelineConfig(ocr=FakeOCR(ocr), writer=writer)
    )

    assert result.status == "pending_review"
    assert result.pairs == []
    assert result.artifact_map is not None
    assert result.artifact_map.units == []
    assert "E001" in result.alarms
    assert len(result.artifact_map.unbound_seqs) == 2
    assert all(
        item["reason"] == "no_view" for item in result.artifact_map.unbound_seqs
    )
    assert writer.images == []


def test_negative_writer_error_single_line_fails_closed(tmp_path) -> None:
    path = line_image(
        tmp_path / "writer_raises.png", size=(160, 120), boxes=[(30, 20, 90, 80)]
    )
    writer = FakeWriter(fail_image=OSError("disk full"))
    fig = figure(
        path,
        caption="图2-1-5 铜鼎（M4:6）",
        body=[para("p1", "铜鼎标本M4:6，通高10厘米。")],
    )

    result = process_figure(fig, PipelineConfig(writer=writer))

    assert result.status == "failed"
    assert result.pairs == []
    assert result.conflicts == ["compose_failed:OSError"]
    assert writer.images == []


def test_negative_missing_artifact_single_line_pends_e005(
    tmp_path, monkeypatch
) -> None:
    """No resolvable artifact id on the single-artifact route -> E005, no guess.

    Real classification sends a zero-id figure to L4 (archive), so the work line
    is pinned here to exercise the defensive ``no_artifact_id`` branch.
    """
    monkeypatch.setattr(
        "archaeopairs.pipeline.classify",
        lambda *_args, **_kwargs: (ImageType.SINGLE_PLATE, WorkLine.SINGLE_PLATE),
    )
    path = line_image(tmp_path / "no_artifact.png")
    writer = FakeWriter()
    fig = figure(path, caption="图版204 陶罐", note=None, body=[])

    result = process_figure(fig, PipelineConfig(writer=writer))

    assert result.status == "pending_review"
    assert result.image_type is ImageType.SINGLE_PLATE
    assert result.work_line is WorkLine.SINGLE_PLATE
    assert result.pairs == []
    assert result.artifact_map is None
    assert result.alarms == ["E005"]
    assert result.conflicts == ["no_artifact_id"]
    assert writer.images == []


def test_negative_multiple_artifacts_single_line_pends_e005(
    tmp_path, monkeypatch
) -> None:
    """A single-artifact route that resolves two ids is E005 pending, not guessed."""
    monkeypatch.setattr(
        "archaeopairs.pipeline.classify",
        lambda *_args, **_kwargs: (ImageType.SINGLE_PLATE, WorkLine.SINGLE_PLATE),
    )
    path = line_image(tmp_path / "multi_artifact.png")
    writer = FakeWriter()
    fig = figure(
        path,
        caption="图版204 陶罐",
        note="1. 陶罐（M4:1、M4:2）",
        body=[],
    )

    result = process_figure(fig, PipelineConfig(writer=writer))

    assert result.status == "pending_review"
    assert result.pairs == []
    assert result.artifact_map is None
    assert result.alarms == ["E005"]
    assert result.conflicts == [
        "multiple_artifacts:figure_note:M4:1,M4:2"
    ]
    assert writer.images == []
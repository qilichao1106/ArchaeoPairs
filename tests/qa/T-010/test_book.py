"""T-010 frozen acceptance: ``process_book`` sinks and batch isolation.

A book is written as one ``pairs`` call and one ``ledger`` call; a single figure
raising (OCR error or Writer error) must not abort the remaining figures and
must surface as ``FigureResult.status == "failed"`` (card §2 L1/process_book).
"""

from __future__ import annotations

from archaeopairs.pipeline import PipelineConfig, process_book

from t010_synthetic import (
    FakeOCR,
    FakeWriter,
    figure,
    line_image,
    ocr_result,
    para,
    pair_rows,
    scale_bar,
    seq_label,
)


def _l1_figure(tmp_path):
    path = line_image(
        tmp_path / "book_l1.png",
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
        figure_id="fig-l1",
    )
    return fig, ocr


def _l2_figure(tmp_path):
    path = line_image(
        tmp_path / "book_l2.png", size=(160, 120), boxes=[(30, 20, 90, 80)]
    )
    fig = figure(
        path,
        caption="图2-1-5 铜鼎（M4:6）",
        body=[para("p1", "铜鼎标本M4:6，通高10厘米。")],
        figure_id="fig-l2",
    )
    return fig


def test_process_book_writes_pairs_and_ledger(tmp_path) -> None:
    l1_fig, l1_ocr = _l1_figure(tmp_path)
    l2_fig = _l2_figure(tmp_path)
    writer = FakeWriter()

    results = process_book(
        [l1_fig, l2_fig], PipelineConfig(ocr=FakeOCR(l1_ocr), writer=writer)
    )

    assert [result.status for result in results] == ["output", "output"]
    assert results[0].artifact_map is not None
    assert results[1].artifact_map is None

    # One pairs sink call carrying every emitted Pair of the book.
    assert writer.write_pairs_calls == 1
    assert len(writer.pairs) == 3
    assert {record["artifact_id"] for record in writer.pairs} == {
        "M4:1",
        "M4:2",
        "M4:6",
    }

    # One ledger sink call carrying pair rows plus every stage entry.
    assert writer.write_ledger_calls == 1
    rows = pair_rows(writer.ledger)
    assert len(rows) == 3
    required = {
        "book_id",
        "figure_id",
        "artifact_id",
        "seq",
        "view_ids",
        "scale_ids",
        "line",
        "status",
        "alarms",
    }
    for row in rows:
        assert required <= set(row)
        assert row["status"] == "output"

    kinds = {row["kind"] for row in writer.ledger if "kind" in row}
    assert {
        "figure_input",
        "ocr",
        "views",
        "text_mapping",
        "bindings",
        "scale_bindings",
        "artifact_map",
    } <= kinds


def test_process_book_one_figure_failure_does_not_abort_batch(tmp_path) -> None:
    bad_fig, _bad_ocr = _l1_figure(tmp_path)
    good_fig = _l2_figure(tmp_path)
    writer = FakeWriter()

    results = process_book(
        [bad_fig, good_fig],
        PipelineConfig(ocr=FakeOCR(error=RuntimeError("ocr down")), writer=writer),
    )

    assert len(results) == 2
    assert results[0].status == "failed"
    assert results[0].conflicts == ["pipeline_failed:RuntimeError"]
    assert results[0].pairs == []
    assert results[1].status == "output"
    assert len(results[1].pairs) == 1

    # The batch continued: the good figure's Pair and ledger still reached disk.
    assert writer.write_pairs_calls == 1
    assert writer.write_ledger_calls == 1
    assert [record["artifact_id"] for record in writer.pairs] == ["M4:6"]
    assert len(pair_rows(writer.ledger)) == 1
    assert any(
        row.get("figure_id") == "fig-l2" for row in writer.ledger
    )


def test_process_book_writer_image_error_isolated_to_one_figure(tmp_path) -> None:
    bad_fig, bad_ocr = _l1_figure(tmp_path)
    good_fig = _l2_figure(tmp_path)
    writer = FakeWriter(fail_name_prefix="图一")

    results = process_book(
        [bad_fig, good_fig],
        PipelineConfig(ocr=FakeOCR(bad_ocr), writer=writer),
    )

    assert results[0].status == "failed"
    assert results[0].conflicts == ["pipeline_failed:OSError"]
    assert results[0].pairs == []
    assert results[1].status == "output"
    assert [name for name, _shape in writer.images] == ["图2-1-5_01_M4-6.png"]
    assert [record["artifact_id"] for record in writer.pairs] == ["M4:6"]
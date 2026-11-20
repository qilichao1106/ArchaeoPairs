"""T-011 frozen acceptance: ``run_book`` end to end with a synthetic book.

The real :class:`~archaeopairs.output.FileWriter` is used (that is the point of
T-011); OCR is always :class:`FakeOCR`, so no Paddle/VLM/network code runs.  A
standard L1 book must yield two Pairs, two PNGs and two JSONL sinks; an L4 book
must yield zero Pairs and never call OCR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from archaeopairs.cli import run_book

from t011_synthetic import (
    FakeOCR,
    jsonl_rows,
    l1_ocr,
    make_l1_book,
    make_l4_book,
    make_mixed_book,
    pair_ledger_rows,
    validate_pair,
)


def test_run_book_l1_writes_two_pairs_two_pngs_and_jsonl(tmp_path) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"
    make_l1_book(books, "bookA")
    ocr = FakeOCR(l1_ocr())

    summary = run_book("bookA", books_dir=books, out_dir=out, ocr=ocr)

    assert summary["book"] == "bookA"
    assert summary["figures"] == 1
    assert summary["pairs"] == 2
    assert summary["statuses"] == {
        "failed": 0,
        "pending_review": 0,
        "output": 1,
        "excluded": 0,
    }
    assert len(ocr.calls) == 1
    assert Path(summary["outputs"]["media_root"]) == books / "bookA"
    assert summary["outputs"]["pairs_jsonl"] == str(out / "pairs.jsonl")
    assert summary["outputs"]["ledger_jsonl"] == str(out / "ledger.jsonl")
    assert summary["outputs"]["images"] == [
        "pairs/图一_1_M4-1.png",
        "pairs/图一_2_M4-2.png",
    ]

    # Two real PNGs, no more and no fewer, under the book output directory.
    pngs = sorted((out / "pairs").glob("*.png"))
    assert [path.name for path in pngs] == ["图一_1_M4-1.png", "图一_2_M4-2.png"]
    assert all(path.read_bytes().startswith(b"\x89PNG") for path in pngs)

    pairs = jsonl_rows(out / "pairs.jsonl")
    assert len(pairs) == 2
    assert [row["artifact_id"] for row in pairs] == ["M4:1", "M4:2"]
    assert [row["image_path"] for row in pairs] == summary["outputs"]["images"]
    assert all(row["status"] == "output" for row in pairs)
    assert all(row["book_id"] == "bookA" for row in pairs)
    for row in pairs:
        validate_pair(row)

    ledger = jsonl_rows(out / "ledger.jsonl")
    pair_rows = pair_ledger_rows(ledger)
    assert len(pair_rows) == 2
    assert {row["artifact_id"] for row in pair_rows} == {"M4:1", "M4:2"}
    kinds = {row["kind"] for row in ledger if "kind" in row}
    assert {
        "figure_input",
        "ocr",
        "views",
        "text_mapping",
        "bindings",
        "scale_bindings",
        "artifact_map",
    } <= kinds


def test_run_book_l4_writes_zero_pairs_and_never_calls_ocr(tmp_path) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"
    make_l4_book(books, "bookL4")
    ocr = FakeOCR(error=AssertionError("L4 must not call OCR"))

    summary = run_book("bookL4", books_dir=books, out_dir=out, ocr=ocr)

    assert summary["book"] == "bookL4"
    assert summary["figures"] == 1
    assert summary["pairs"] == 0
    assert summary["statuses"]["excluded"] == 1
    assert summary["statuses"]["output"] == 0
    assert summary["outputs"]["images"] == []
    assert ocr.calls == []

    assert (out / "pairs.jsonl").is_file()
    assert (out / "pairs.jsonl").read_text(encoding="utf-8") == ""
    assert list((out / "pairs").glob("*.png")) == []

    ledger = jsonl_rows(out / "ledger.jsonl")
    assert [row.get("kind") for row in ledger] == ["figure_input"]
    assert ledger[0]["figure_id"] == "bookL4:fig_l4"
    assert pair_ledger_rows(ledger) == []


def test_run_book_limit_truncates_figures_before_processing(tmp_path) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"
    make_mixed_book(books, "bookMixed")
    ocr = FakeOCR(l1_ocr())

    summary = run_book(
        "bookMixed", books_dir=books, out_dir=out, ocr=ocr, limit=1
    )

    # The L1 figure runs; the second (L4) figure never reaches the pipeline.
    assert summary["figures"] == 1
    assert summary["pairs"] == 2
    assert summary["statuses"]["output"] == 1
    assert summary["statuses"]["excluded"] == 0
    assert len(jsonl_rows(out / "pairs.jsonl")) == 2


def test_run_book_missing_book_raises_before_writing(tmp_path) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"

    with pytest.raises(FileNotFoundError, match="data.xml"):
        run_book("no-such-book", books_dir=books, out_dir=out)

    assert not out.exists()
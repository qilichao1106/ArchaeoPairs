"""T-011 frozen acceptance: ``run_books`` batch isolation.

Each discovered book writes into ``<out_dir>/<book>/``; a book that cannot even
start (malformed XML) must be reported under ``errors`` while the remaining
books still complete.  OCR is fake for every call.
"""

from __future__ import annotations

from pathlib import Path

from archaeopairs.cli import run_books

from t011_synthetic import (
    FakeOCR,
    jsonl_rows,
    l1_ocr,
    make_bad_book,
    make_l1_book,
)


def test_run_books_isolates_each_book_under_its_own_subdirectory(tmp_path) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"
    make_l1_book(books, "bookA")
    make_l1_book(
        books,
        "bookB",
        caption="图二 出土器物",
        note="1. 陶豆（M4:3） 2. 陶壶（M4:4）",
        body_paras=("陶豆标本M4:3，泥质灰陶。", "陶壶标本M4:4，夹砂灰陶。"),
        image_name="fig_b.png",
    )

    summary = run_books(books_dir=books, out_dir=out, ocr=FakeOCR(l1_ocr()))

    assert summary["books"] == ["bookA", "bookB"]
    assert summary["errors"] == {}
    assert summary["figures"] == 2
    assert summary["pairs"] == 4
    assert summary["statuses"]["output"] == 2
    assert summary["statuses"]["excluded"] == 0
    assert {
        Path(result["outputs"]["out_dir"]).name for result in summary["results"]
    } == {"bookA", "bookB"}

    images_by_book: dict[str, set[str]] = {}
    for book in ("bookA", "bookB"):
        subdir = out / book
        assert (subdir / "pairs.jsonl").is_file()
        assert (subdir / "ledger.jsonl").is_file()
        pairs = jsonl_rows(subdir / "pairs.jsonl")
        assert len(pairs) == 2
        assert {row["book_id"] for row in pairs} == {book}
        pngs = sorted((subdir / "pairs").glob("*.png"))
        assert len(pngs) == 2
        images_by_book[book] = {path.name for path in pngs}

    # The two books' filenames do not collide even though both use seqs 1/2.
    assert images_by_book["bookA"].isdisjoint(images_by_book["bookB"])


def test_run_books_records_bad_book_in_errors_and_keeps_going(tmp_path) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"
    make_l1_book(books, "good")
    make_bad_book(books, "bad")

    summary = run_books(books_dir=books, out_dir=out, ocr=FakeOCR(l1_ocr()))

    assert summary["books"] == ["good"]
    assert set(summary["errors"]) == {"bad"}
    assert summary["errors"]["bad"].startswith("ParseError:")
    assert summary["figures"] == 1
    assert summary["pairs"] == 2

    # The good book still reached disk; the bad one never created a subtree.
    assert (out / "good" / "pairs.jsonl").is_file()
    assert len(jsonl_rows(out / "good" / "pairs.jsonl")) == 2
    assert not (out / "bad").exists()
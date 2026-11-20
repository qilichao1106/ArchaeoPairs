"""T-011 frozen acceptance: CLI parser wiring and exit codes.

``build_parser`` must expose ``--book`` (required for ``run-book``),
``--books-dir``, ``--media-root``, ``--limit``, ``--out`` and ``--no-vl``.
``main`` must return 1 when the book cannot be started and 0 for a completed
run, even if figures land in ``pending_review``.  The normal-run test replaces
the production OCR factory with :class:`FakeOCR`, so no model is loaded.
"""

from __future__ import annotations

import json

import pytest

from archaeopairs import cli
from archaeopairs.cli import build_parser, main

from t011_synthetic import FakeOCR, l1_ocr, make_l1_book


def test_parser_run_book_accepts_documented_options() -> None:
    args = build_parser().parse_args(
        [
            "run-book",
            "--book",
            "bookA",
            "--books-dir",
            "some-books",
            "--media-root",
            "some-media",
            "--limit",
            "3",
            "--out",
            "some-out",
            "--no-vl",
        ]
    )

    assert args.command == "run-book"
    assert args.book == "bookA"
    assert args.books_dir == "some-books"
    assert args.media_root == "some-media"
    assert args.limit == 3
    assert args.out_dir == "some-out"
    assert args.no_vl is True


def test_parser_run_books_defaults_and_common_flags() -> None:
    parser = build_parser()
    defaults = parser.parse_args(["run-books"])

    assert defaults.command == "run-books"
    assert defaults.books_dir == "books"
    assert defaults.media_root is None
    assert defaults.limit is None
    assert defaults.out_dir == "out"
    assert defaults.no_vl is False

    flagged = parser.parse_args(["run-books", "--limit", "4", "--no-vl"])
    assert flagged.limit == 4
    assert flagged.no_vl is True


def test_main_passes_parsed_options_to_run_book(monkeypatch, capsys) -> None:
    calls: dict = {}

    def fake_run_book(
        book,
        *,
        books_dir="books",
        media_root=None,
        limit=None,
        out_dir="out",
        ocr=None,
        vl=True,
    ):
        calls.update(
            book=book,
            books_dir=books_dir,
            media_root=media_root,
            limit=limit,
            out_dir=out_dir,
            ocr=ocr,
            vl=vl,
        )
        return {"book": book}

    monkeypatch.setattr(cli, "run_book", fake_run_book)

    code = main(
        [
            "run-book",
            "--book",
            "B",
            "--books-dir",
            "BD",
            "--media-root",
            "MR",
            "--limit",
            "7",
            "--out",
            "OUT",
            "--no-vl",
        ]
    )

    assert code == 0
    assert calls == {
        "book": "B",
        "books_dir": "BD",
        "media_root": "MR",
        "limit": 7,
        "out_dir": "OUT",
        "ocr": None,
        "vl": False,
    }
    assert json.loads(capsys.readouterr().out) == {"book": "B"}


def test_main_normal_run_book_exits_0(tmp_path, monkeypatch, capsys) -> None:
    books = tmp_path / "books"
    out = tmp_path / "out"
    make_l1_book(books, "bookA")
    seen: list[bool] = []

    def fake_default_ocr(*, vl=True):
        seen.append(vl)
        return FakeOCR(l1_ocr())

    monkeypatch.setattr(cli, "default_ocr", fake_default_ocr)

    code = main(
        [
            "run-book",
            "--book",
            "bookA",
            "--books-dir",
            str(books),
            "--media-root",
            str(books / "bookA"),
            "--out",
            str(out),
            "--no-vl",
        ]
    )

    assert code == 0
    assert seen == [False]  # --no-vl reached default_ocr
    payload = json.loads(capsys.readouterr().out)
    assert payload["book"] == "bookA"
    assert payload["figures"] == 1
    assert payload["pairs"] == 2
    assert (out / "pairs.jsonl").is_file()
    assert len(list((out / "pairs").glob("*.png"))) == 2


def test_main_missing_book_exits_1(tmp_path, capsys) -> None:
    books = tmp_path / "books"
    books.mkdir()
    out = tmp_path / "out"

    with pytest.raises(SystemExit) as info:
        main(
            [
                "run-book",
                "--book",
                "missing-book",
                "--books-dir",
                str(books),
                "--out",
                str(out),
            ]
        )

    assert info.value.code == 1
    assert "data.xml not found" in capsys.readouterr().err
    assert not out.exists()


def test_parser_run_book_requires_book() -> None:
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args(["run-book", "--books-dir", "books"])

    assert info.value.code == 2


def test_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args([])

    assert info.value.code == 2


@pytest.mark.parametrize("value", ["abc", "1.5", "-1", ""])
def test_parser_limit_rejects_non_positive_integer(value: str) -> None:
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args(
            ["run-book", "--book", "bookA", "--limit", value]
        )

    assert info.value.code == 2
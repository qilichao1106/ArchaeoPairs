"""Command-line entry point and book orchestration glue (T-011, AC-04/05/07).

Thin layer on top of :func:`archaeopairs.pipeline.process_book`: it locates
``books/<book>/data.xml``, parses it, runs the pipeline with a
:class:`~archaeopairs.output.FileWriter` and reports a JSON summary.  OCR is
injectable so tests and selfchecks never touch a real model; the default is the
hybrid VLM + Paddle provider (``--no-vl`` drops the VLM half).

Exit codes: ``0`` whenever the run completed, even if some figures landed in
``pending_review``; ``2`` for usage errors; ``1`` only when the run could not
be started at all (missing book, unreadable XML, unwritable output).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from archaeopairs.ingest import parse_book
from archaeopairs.output import FileWriter
from archaeopairs.pipeline import PipelineConfig, Writer, process_book

__all__ = ["default_ocr", "main", "run_book", "run_books"]

# Figure statuses counted in every summary (see ``FigureResult.status``).
_STATUS_KEYS = ("failed", "pending_review", "output", "excluded")


def default_ocr(*, vl: bool = True):
    """Build the production OCR provider: hybrid VLM+Paddle, or Paddle only."""
    from archaeopairs.ocr import (
        HybridOCRProvider,
        PaddleOCRProvider,
        VlmOCRProvider,
    )

    if not vl:
        return PaddleOCRProvider()
    # Runtime OCR is VLM-first (CR-001); Paddle stays available via --no-vl and
    # the hybrid provider remains injectable for experiments.
    from archaeopairs.vlm.client import VlmClient

    return VlmOCRProvider(VlmClient())


def _resolve_books_dir(books_dir: str | Path) -> Path:
    base = Path(books_dir)
    if not base.is_absolute() and not base.exists():
        # ``books/`` lives at the project root, one level above ``src/``.
        candidate = Path(__file__).resolve().parents[2] / base
        if candidate.exists():
            return candidate
    return base


def _resolve_media_root(books_dir: Path, book: str, media_root: str | Path | None) -> Path:
    if media_root is not None:
        return Path(media_root)
    # Default ingestion rule: media paths are relative to the book directory.
    return books_dir / book


def _summarise(
    book: str, results, out_dir: Path, media_root: Path,
) -> dict[str, Any]:
    statuses = {key: 0 for key in _STATUS_KEYS}
    for result in results:
        status = str(getattr(result, "status", ""))
        if status in statuses:
            statuses[status] += 1
    pairs = [pair for result in results for pair in result.pairs]
    written = sorted(
        str(getattr(pair, "image_path", "") or "")
        for pair in pairs
        if getattr(pair, "image_path", None)
    )
    return {
        "book": book,
        "figures": len(results),
        "pairs": len(pairs),
        "statuses": statuses,
        "outputs": {
            "out_dir": str(out_dir),
            "media_root": str(media_root),
            "pairs_jsonl": str(out_dir / "pairs.jsonl"),
            "ledger_jsonl": str(out_dir / "ledger.jsonl"),
            "images": written,
        },
    }


def _run_one(
    book: str, *, books_dir: str | Path, media_root: str | Path | None,
    limit: int | None, out_dir: str | Path, ocr: Any, vl: bool,
    writer: Writer | None = None,
) -> dict[str, Any]:
    books_root = _resolve_books_dir(books_dir)
    xml_path = books_root / book / "data.xml"
    if not xml_path.is_file():
        raise FileNotFoundError(f"book data.xml not found: {xml_path}")
    root = _resolve_media_root(books_root, book, media_root)
    figures = parse_book(xml_path, book, root)
    if limit is not None:
        figures = figures[: max(0, int(limit))]
    out_path = Path(out_dir)
    cfg = PipelineConfig(
        ocr=ocr if ocr is not None else default_ocr(vl=vl),
        writer=writer if writer is not None else FileWriter(out_path),
        name_registry={},
    )
    results = process_book(figures, cfg)
    return _summarise(book, results, out_path, root)


def run_book(
    book: str, *, books_dir: str | Path = "books",
    media_root: str | Path | None = None, limit: int | None = None,
    out_dir: str | Path = "out", ocr: Any = None, vl: bool = True,
    writer: Writer | None = None,
) -> dict[str, Any]:
    """Run one book through the pipeline and write its files; return a summary."""
    return _run_one(
        book, books_dir=books_dir, media_root=media_root, limit=limit,
        out_dir=out_dir, ocr=ocr, vl=vl, writer=writer,
    )


def _discover_books(books_dir: Path) -> list[str]:
    if not books_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in books_dir.iterdir()
        if child.is_dir() and (child / "data.xml").is_file()
    )


def run_books(
    *, books_dir: str | Path = "books", media_root: str | Path | None = None,
    limit: int | None = None, out_dir: str | Path = "out", ocr: Any = None,
    vl: bool = True,
) -> dict[str, Any]:
    """Run every ``books_dir/*/data.xml`` book; aggregate the summaries.

    Each book writes into its own ``<out_dir>/<book>/`` subtree so files never
    collide.  A book that cannot even start is recorded under ``errors`` while
    the remaining books still run.
    """
    root = _resolve_books_dir(books_dir)
    books = _discover_books(root)
    totals = {key: 0 for key in _STATUS_KEYS}
    books_out: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for book in books:
        try:
            summary = _run_one(
                book, books_dir=root, media_root=media_root, limit=limit,
                out_dir=Path(out_dir) / book, ocr=ocr, vl=vl,
            )
        except Exception as exc:  # noqa: BLE001 - one book must not stop the batch
            errors[book] = f"{type(exc).__name__}: {exc}"
            continue
        books_out.append(summary)
        for key in totals:
            totals[key] += int(summary["statuses"].get(key, 0))
    return {
        "books_dir": str(root),
        "books": [summary["book"] for summary in books_out],
        "figures": sum(summary["figures"] for summary in books_out),
        "pairs": sum(summary["pairs"] for summary in books_out),
        "statuses": totals,
        "results": books_out,
        "errors": errors,
    }


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser (``run-book`` / ``run-books`` subcommands)."""
    parser = argparse.ArgumentParser(
        prog="archaeopairs",
        description="ArchaeoPairs: figure/text pair extraction.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument("--books-dir", default="books", help="books root (default: books)")
        cmd.add_argument("--media-root", default=None, help="media root (default: <books-dir>/<book>)")
        cmd.add_argument("--limit", type=_positive_int, default=None, help="max figures per book")
        cmd.add_argument("--out", dest="out_dir", default="out", help="output dir (default: out)")
        cmd.add_argument("--no-vl", action="store_true", help="disable the VLM and use PaddleOCR only")

    one = sub.add_parser("run-book", help="run a single book")
    one.add_argument("--book", required=True, help="book id (= subdirectory of --books-dir)")
    _common(one)

    many = sub.add_parser("run-books", help="run every book under --books-dir")
    _common(many)
    return parser


def _call(func, **kwargs):
    import inspect

    params = inspect.signature(func).parameters
    return func(**{key: value for key, value in kwargs.items() if key in params})


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` (default ``sys.argv``), run, print JSON; return exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    common = {
        "books_dir": args.books_dir,
        "media_root": args.media_root,
        "limit": args.limit,
        "out_dir": args.out_dir,
        "vl": not args.no_vl,
    }
    try:
        if args.command == "run-book":
            summary = _call(run_book, book=args.book, **common)
        else:
            summary = _call(run_books, **common)
    except (FileNotFoundError, OSError, ValueError) as exc:
        parser.exit(1, f"archaeopairs: error: {type(exc).__name__}: {exc}\n")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

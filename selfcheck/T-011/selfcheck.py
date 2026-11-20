"""Selfcheck for T-011 (AC-04/05/07): FileWriter, run_book, CLI parsing.

Everything is synthetic and offline: a throw-away book tree with Chinese names
is written under a temp dir, figures are drawn with PIL, and OCR is a fake that
returns a fixed :class:`OcrResult` (never a real model).  Run from the project
root::

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-011/selfcheck.py

Prints ``SELFCHECK OK`` on success and exits non-zero on the first failure.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from archaeopairs.cli import build_parser, main, run_book  # noqa: E402
from archaeopairs.models import OcrResult, ScaleBar, SeqLabel  # noqa: E402
from archaeopairs.output import FileWriter  # noqa: E402

PAIR_SCHEMA = REPO_ROOT / "contracts" / "pair_record.schema.json"
book_id = "测试书"


def _line_png(path: Path) -> None:
    """White canvas with two black squares and a scale bar (reads as a line drawing)."""
    image = Image.new("RGB", (300, 200), "white")
    draw = ImageDraw.Draw(image)
    for box in [(30, 30, 90, 90), (160, 30, 220, 90), (20, 160, 280, 164)]:
        draw.rectangle(box, fill="black")
    image.save(path)


def _blank_png(path: Path) -> None:
    Image.new("RGB", (300, 200), "white").save(path)


DATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<book>
  <figure>
    <figure-title>图一 出土器物</figure-title>
    <figure-note>1. 陶豆（M4:1） 2. 陶壶（M4:2）</figure-note>
    <mediaobject><imageobject>
      <imagedata fileref="media/线图.png"/>
    </imageobject></mediaobject>
  </figure>
  <figure>
    <figure-title>图二 纹饰</figure-title>
    <figure-note>0 8厘米</figure-note>
    <mediaobject><imageobject>
      <imagedata fileref="media/空白.png"/>
    </imageobject></mediaobject>
  </figure>
  <para>陶豆标本M4:1，泥质灰陶。</para>
  <para>陶壶标本M4:2，夹砂灰陶。</para>
</book>
"""


class FakeOCR:
    """Fixed OCR result; records every call. No network, no model."""

    def __init__(self, result: OcrResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def read(self, image_path):
        self.calls.append(str(image_path))
        return self.result


def _fake_ocr() -> FakeOCR:
    return FakeOCR(
        OcrResult(
            seqs=[
                SeqLabel(text="1", bbox=(40, 40, 50, 50), conf=0.99),
                SeqLabel(text="2", bbox=(170, 40, 180, 50), conf=0.99),
            ],
            scales=[
                ScaleBar(
                    text="0 5厘米", bbox=(15, 155, 285, 175), value=5.0,
                    unit="厘米", prefix_nos=["1", "2"],
                )
            ],
            source="fake",
        )
    )


def _check_pairs_shape(pairs: list[dict]) -> None:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(json.loads(PAIR_SCHEMA.read_text(encoding="utf-8")))
    for row in pairs:
        assert (errors := list(validator.iter_errors(row))) == [], [e.message for e in errors]



def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main_check() -> None:
    assert PAIR_SCHEMA.is_file(), f"missing schema: {PAIR_SCHEMA}"

    with tempfile.TemporaryDirectory(prefix="自检_") as tmp:
        root = Path(tmp) / "中文路径_书库"
        book_dir = root / book_id
        media = book_dir / "media"
        media.mkdir(parents=True)
        _line_png(media / "线图.png")
        _blank_png(media / "空白.png")
        (book_dir / "data.xml").write_text(DATA_XML, encoding="utf-8")
        out_dir = Path(tmp) / "输出"

        # --- 1. FileWriter in a Chinese path --------------------------------
        writer = FileWriter(out_dir / "直接写入")
        rel = writer.write_image("图一_1_M4-1.png", np.zeros((10, 12, 3), dtype=np.uint8))
        assert rel == "pairs/图一_1_M4-1.png", rel
        assert (out_dir / "直接写入" / rel).is_file()
        writer.write_pairs([{"artifact_id": "M4:1"}])
        writer.write_ledger([])
        assert _read_jsonl(out_dir / "直接写入" / "pairs.jsonl") == [{"artifact_id": "M4:1"}]
        assert (out_dir / "直接写入" / "ledger.jsonl").read_text(encoding="utf-8") == ""

        # --- 2. run_book end to end with the fake OCR ------------------------
        ocr = _fake_ocr()
        summary = run_book(
            book_id, books_dir=root, limit=1, out_dir=out_dir / "单书",
            ocr=ocr, vl=False,
        )
        assert ocr.calls, "L1 figure must call the injected OCR"
        assert summary["book"] == book_id, summary
        assert summary["figures"] == 1, summary
        assert summary["pairs"] == 2, summary["pairs"]
        assert summary["statuses"] == {
            "failed": 0, "pending_review": 0, "output": 1, "excluded": 0,
        }, summary["statuses"]

        images = summary["outputs"]["images"]
        assert sorted(images) == [
            "pairs/图一_1_M4-1.png", "pairs/图一_2_M4-2.png",
        ], images
        for image_rel in images:
            assert (out_dir / "单书" / image_rel).is_file(), image_rel

        pairs = _read_jsonl(out_dir / "单书" / "pairs.jsonl")
        ledger = _read_jsonl(out_dir / "单书" / "ledger.jsonl")
        assert len(pairs) == 2, len(pairs)
        assert [row["image_path"] for row in pairs] == sorted(images), pairs
        assert len([row for row in ledger if "artifact_id" in row and "kind" not in row]) == 2
        _check_pairs_shape(pairs)

        # --- 3. run_book L4 (no pair), plus limit=2 vs limit=1 ---------------
        full = run_book(book_id, books_dir=root, out_dir=out_dir / "全部", ocr=_fake_ocr(), vl=False)
        assert full["figures"] == 2, full["figures"]
        assert full["pairs"] == 2, full["pairs"]
        assert full["statuses"]["excluded"] == 1, full["statuses"]
        assert (out_dir / "全部" / "pairs.jsonl").is_file()

    # --- 4. argparse surface -----------------------------------------------
    parser = build_parser()
    one = parser.parse_args(
        ["run-book", "--book", "bk", "--books-dir", "b", "--media-root", "m",
         "--limit", "3", "--out", "o", "--no-vl"]
    )
    assert one.command == "run-book"
    assert (one.book, one.books_dir, one.media_root, one.limit, one.out_dir) == (
        "bk", "b", "m", 3, "o"
    )
    assert one.no_vl is True
    many = parser.parse_args(["run-books"])
    assert many.command == "run-books" and many.no_vl is False and many.limit is None

    # Round-trip through main() on an empty books dir: JSON summary, exit 0.
    with tempfile.TemporaryDirectory(prefix="空库_") as empty:
        code = main(["run-books", "--books-dir", empty, "--out", str(Path(empty) / "o")])
        assert code == 0, code
    try:
        main(["run-book", "--book", "不存在"])
    except SystemExit as exit_signal:
        assert exit_signal.code == 1, exit_signal.code
    else:  # pragma: no cover - must not reach here
        raise AssertionError("missing book must exit non-zero")


if __name__ == "__main__":
    main_check()
    print("SELFCHECK OK", flush=True)

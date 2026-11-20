"""Synthetic books, line drawings and fake OCR for the frozen T-011 tests.

Nothing here reads the real ``books/`` tree, touches the network, or constructs
PaddleOCR / a VLM client.  A book is a temporary ``<books>/<book>/data.xml``
plus one or more PNGs under ``<book>/media/``; OCR is a pre-built
:class:`~archaeopairs.models.OcrResult` returned by :class:`FakeOCR`.

The L1 fixture matches the geometry used by the frozen T-010 suite: two black
line-art rectangles with seq labels ``1`` / ``2`` and one shared scale bar whose
``prefix_nos`` names both seqs.  With the matching figure note/body text this
produces exactly two clean Pairs.  The L4 fixture has no artifact number in its
caption/note and is therefore archived without OCR.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel

_REPO_ROOT = Path(__file__).resolve().parents[3]
PAIR_SCHEMA = _REPO_ROOT / "contracts" / "pair_record.schema.json"

L1_CAPTION = "图一 出土器物"
L1_NOTE = "1. 陶豆（M4:1） 2. 陶壶（M4:2）"
L1_BODY = (
    "陶豆标本M4:1，泥质灰陶。",
    "陶壶标本M4:2，夹砂灰陶。",
)

L4_CAPTION = "图五 纹饰"
L4_NOTE = "0 8厘米"


# --- images ----------------------------------------------------------------


def line_image(
    path,
    *,
    size: tuple[int, int] = (300, 200),
    boxes=(),
    bar=None,
    glyphs=(),
) -> Path:
    """White RGB canvas with black filled regions (pure line art)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for box in (*boxes, *glyphs):
        draw.rectangle(tuple(int(value) for value in box), fill="black")
    if bar is not None:
        draw.rectangle(tuple(int(value) for value in bar), fill="black")
    image.save(path)
    return path


# --- OCR -------------------------------------------------------------------


def l1_ocr() -> OcrResult:
    """The two seq labels and the shared scale bar for the standard L1 image."""
    return OcrResult(
        seqs=[
            SeqLabel(text="1", bbox=(40, 40, 50, 50), conf=0.99),
            SeqLabel(text="2", bbox=(170, 40, 180, 50), conf=0.99),
        ],
        scales=[
            ScaleBar(
                text="0 5厘米",
                bbox=(15, 155, 285, 175),
                value=5.0,
                unit="厘米",
                prefix_nos=["1", "2"],
            )
        ],
        source="fake",
    )


class FakeOCR:
    """Return one pre-built result, record calls, optionally raise."""

    def __init__(
        self,
        result: OcrResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def read(self, image_path):
        self.calls.append(str(image_path))
        if self.error is not None:
            raise self.error
        return self.result


# --- books -----------------------------------------------------------------


def make_book(
    books_dir: str | Path,
    book_id: str,
    *,
    figures: list[dict],
    body_paras=(),
) -> Path:
    """Write ``<books_dir>/<book_id>/data.xml``; images must already exist.

    ``figures`` items use ``caption`` / ``note`` / ``fileref`` keys.  All
    ``body_paras`` strings become non-empty ``<para>`` elements, which
    :func:`archaeopairs.ingest.parse_book` numbers ``p1``..``pN``.
    """
    book_dir = Path(books_dir) / book_id
    book_dir.mkdir(parents=True, exist_ok=True)

    para_xml = "\n".join(
        f"      <para>{escape(text)}</para>" for text in body_paras
    )
    figure_xml = "\n".join(
        "    <figure>\n"
        f"      <figure-title>{escape(spec.get('caption') or '')}</figure-title>\n"
        f"      <figure-note>{escape(spec.get('note') or '')}</figure-note>\n"
        "      <mediaobject><imageobject>"
        f"<imagedata fileref=\"{escape(spec['fileref'])}\"/>"
        "</imageobject></mediaobject>\n"
        "    </figure>"
        for spec in figures
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<book id="{escape(book_id)}">\n'
        "  <chapter>\n"
        + (para_xml + "\n" if para_xml else "")
        + (figure_xml + "\n" if figure_xml else "")
        + "  </chapter>\n"
        "</book>\n"
    )
    (book_dir / "data.xml").write_text(xml, encoding="utf-8")
    return book_dir


def _l1_spec(caption: str, note: str, fileref: str) -> dict:
    return {"caption": caption, "note": note, "fileref": fileref}


def make_l1_book(
    books_dir: str | Path,
    book_id: str = "bookA",
    *,
    caption: str = L1_CAPTION,
    note: str = L1_NOTE,
    body_paras=L1_BODY,
    image_name: str = "fig_l1.png",
) -> Path:
    """Two numbered line-art views plus a shared scale bar (L1, two artifacts)."""
    book_dir = Path(books_dir) / book_id
    line_image(
        book_dir / "media" / image_name,
        boxes=[(30, 30, 90, 90), (160, 30, 220, 90)],
        bar=(20, 160, 280, 164),
    )
    return make_book(
        books_dir,
        book_id,
        figures=[_l1_spec(caption, note, f"media/{image_name}")],
        body_paras=body_paras,
    )


def make_l4_book(
    books_dir: str | Path,
    book_id: str = "bookL4",
    *,
    caption: str = L4_CAPTION,
    note: str = L4_NOTE,
    image_name: str = "fig_l4.png",
) -> Path:
    """A figure with no artifact number: L4, zero Pairs, no OCR call."""
    book_dir = Path(books_dir) / book_id
    line_image(
        book_dir / "media" / image_name,
        boxes=[(30, 30, 90, 90)],
    )
    return make_book(
        books_dir,
        book_id,
        figures=[_l1_spec(caption, note, f"media/{image_name}")],
        body_paras=(),
    )


def make_mixed_book(
    books_dir: str | Path,
    book_id: str = "bookMixed",
) -> Path:
    """One L1 figure followed by one L4 figure; used for ``limit`` behaviour."""
    book_dir = Path(books_dir) / book_id
    line_image(
        book_dir / "media" / "fig_l1.png",
        boxes=[(30, 30, 90, 90), (160, 30, 220, 90)],
        bar=(20, 160, 280, 164),
    )
    line_image(
        book_dir / "media" / "fig_l4.png",
        boxes=[(30, 30, 90, 90)],
    )
    return make_book(
        books_dir,
        book_id,
        figures=[
            _l1_spec(L1_CAPTION, L1_NOTE, "media/fig_l1.png"),
            _l1_spec(L4_CAPTION, L4_NOTE, "media/fig_l4.png"),
        ],
        body_paras=L1_BODY,
    )


def make_bad_book(books_dir: str | Path, book_id: str = "bookBad") -> Path:
    """A discovered book whose ``data.xml`` is malformed (parse error)."""
    book_dir = Path(books_dir) / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "data.xml").write_text(
        "<book><figure><figure-title>unterminated", encoding="utf-8"
    )
    return book_dir


# --- assertions helpers ----------------------------------------------------


def jsonl_rows(path: str | Path) -> list[dict]:
    """Read one JSON object per non-empty line (UTF-8)."""
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def pair_ledger_rows(rows: list[dict]) -> list[dict]:
    """Ledger rows that describe a Pair (stage entries carry ``kind``)."""
    return [row for row in rows if "artifact_id" in row and "kind" not in row]


def validate_pair(pair) -> None:
    """Assert one Pair (model or JSONL dict) validates against the frozen schema."""
    from jsonschema import Draft202012Validator

    schema = json.loads(PAIR_SCHEMA.read_text(encoding="utf-8"))
    instance = pair.model_dump(mode="json") if hasattr(pair, "model_dump") else pair
    errors = list(Draft202012Validator(schema).iter_errors(instance))
    assert errors == [], [error.message for error in errors]
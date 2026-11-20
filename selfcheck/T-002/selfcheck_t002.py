"""Self-check for T-002: XML ingestion + artifact counting + five-way routing.

Portable: run from the project root with

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-002/selfcheck_t002.py

It builds a temporary DocBook XML (namespaced) and a sparse line drawing, then
asserts the ingestion and classification contracts required by card T-002 and
prints the key fields before ``SELFCHECK OK``. It writes nothing into the repo.

Standard output is forced to UTF-8 inside the script (``sys.stdout.reconfigure``)
so Chinese captions/notes print correctly on a GBK/CP936 Windows console and in
the redirected log, independent of the console code page.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Force UTF-8 output regardless of the console code page (cp936/GBK on
# Windows) so Chinese field values never turn into mojibake in the log.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - exotic stream
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from archaeopairs.classify.image_type import (  # noqa: E402
    classify,
    classify_image_type,
    count_artifacts,
    work_line_of,
)
from archaeopairs.ingest.xml import parse_book  # noqa: E402
from archaeopairs.models import ImageType, WorkLine  # noqa: E402

# Namespaced DocBook; ``para`` with a blank-only body must be dropped.
XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<book xmlns="http://docbook.org/ns/docbook">
  <chapter>
    <para>M4：6，铜舟，通高10厘米。</para>
    <para>   </para>
    <para>M43：75a、M43：75b，铁削。</para>
    <figure>
      <figure-title>图二一二 铜舟</figure-title>
      <figure-note>1. 铜舟（M4：6）</figure-note>
      <figure-note>0 8厘米</figure-note>
      <mediaobject>
        <imageobject><imagedata fileref="media/fig212.png"/></imageobject>
      </mediaobject>
    </figure>
    <figure>
      <figure-title>无媒体 跳过</figure-title>
    </figure>
    <figure>
      <figure-title>图二一三 铁削</figure-title>
      <figure-note>1、2. 铁削（M43：75a、M43：75b）</figure-note>
      <mediaobject>
        <imageobject><imagedata fileref="media/fig213.png"/></imageobject>
      </mediaobject>
    </figure>
  </chapter>
</book>
"""


def _make_line_image(path: Path) -> None:
    img = Image.new("RGB", (300, 220), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, 30, 200, 190), outline="black", width=1)
    draw.ellipse((120, 80, 160, 120), outline="black", width=1)
    draw.line((60, 200, 260, 200), fill="black", width=1)
    img.save(path)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t002_selfcheck_"))
    (tmp / "media").mkdir()
    xml_path = tmp / "data.xml"
    xml_path.write_text(XML_TEMPLATE, encoding="utf-8")
    _make_line_image(tmp / "media" / "fig212.png")
    _make_line_image(tmp / "media" / "fig213.png")

    figures = parse_book(xml_path, "bookA", media_root=tmp)
    assert [f.figure_id for f in figures] == ["bookA:fig212", "bookA:fig213"], [
        f.figure_id for f in figures
    ]

    first = figures[0]
    assert first.caption == "图二一二 铜舟", repr(first.caption)
    assert first.figure_note == "1. 铜舟（M4：6）\n0 8厘米", repr(first.figure_note)
    assert Path(first.media_path) == (tmp / "media" / "fig212.png").resolve()
    assert [p["id"] for p in first.body_paras] == ["p1", "p2"], first.body_paras
    assert [p["text"] for p in first.body_paras] == [
        "M4：6，铜舟，通高10厘米。",
        "M43：75a、M43：75b，铁削。",
    ], first.body_paras

    # Artifact counting: figure note preferred, caption fallback, dedup, suffix
    # kept, scale/figure-number text never counted.
    assert count_artifacts('1. 铜舟（M4：6）', '0 8厘米') == 1
    # Regression (fix round 1): note has 2 ids, caption has 1 -> note wins.
    assert (
        count_artifacts(
            '图2-1-5 M4出土铜鼎（M4：6）纹饰',
            '1. 陶豆（M4:1） 2. 陶壶（M4:2）',
        )
        == 2
    )
    assert count_artifacts('图二一二', '1、2. 陶豆（M4：2、M4：1）') == 2
    assert count_artifacts('M43:75a、M43:75b、M43:75c', None) == 3
    assert count_artifacts('M39:8-1、M39:8-2', None) == 2
    assert count_artifacts('图二一二 0 8厘米', None) == 0
    # Routing: single / multi by N, line family from pixels, L4 for discarded.
    single = classify_image_type(first.caption, first.figure_note, first.media_path)
    multi = classify_image_type(figures[1].caption, figures[1].figure_note, figures[1].media_path)
    discarded = classify_image_type("图二一二", None, first.media_path)
    assert single == ImageType.SINGLE_LINE, single
    assert multi == ImageType.MULTI_LINE, multi
    assert discarded == ImageType.DISCARDED, discarded

    image_type, line = classify(figures[1].caption, figures[1].figure_note, figures[1].media_path)
    assert (image_type, line) == (ImageType.MULTI_LINE, WorkLine.MULTI_LINE), (image_type, line)
    assert work_line_of(ImageType.MULTI_PLATE) == WorkLine.ARCHIVE
    assert work_line_of(ImageType.SINGLE_PLATE) == WorkLine.SINGLE_PLATE

    print("book_id            :", first.book_id)
    print("figure_ids         :", [f.figure_id for f in figures])
    print("caption            :", first.caption)
    print("figure_note        :", first.figure_note.replace("\n", " | "))
    print("body_para_ids      :", [p["id"] for p in first.body_paras])
    print("artifacts(fig212)  :", count_artifacts(first.caption, first.figure_note))
    print("artifacts(fig213)  :", count_artifacts(figures[1].caption, figures[1].figure_note))
    print("image_type(fig212) :", single.value, "->", work_line_of(single).value)
    print("image_type(fig213) :", multi.value, "->", work_line_of(multi).value)
    print("image_type(no-num) :", discarded.value, "->", work_line_of(discarded).value)
    print("SELFCHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
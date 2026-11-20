"""T-002 parse_book acceptance: namespace-agnostic DocBook ingestion."""

from __future__ import annotations

from pathlib import Path

from archaeopairs.ingest.xml import parse_book
from archaeopairs.models import FigureInput

NAMESPACED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<book xmlns="http://docbook.org/ns/docbook">
  <chapter>
    <para>正文一 <emphasis>强调</emphasis>。</para>
    <para>   </para>
    <section><para>正文二</para></section>
    <figure>
      <figure-title>图二一二 铜舟</figure-title>
      <figure-note>1. 铜舟（M4：6）</figure-note>
      <figure-note>0 8厘米</figure-note>
      <mediaobject>
        <imageobject>
          <imagedata fileref="media/fig212.png"/>
        </imageobject>
      </mediaobject>
    </figure>
    <figure>
      <figure-title>无媒体，必须跳过</figure-title>
    </figure>
    <figure>
      <figure-title>图二一三 铁削</figure-title>
      <mediaobject>
        <imageobject>
          <imagedata fileref="media/sub/fig213.jpg"/>
        </imageobject>
      </mediaobject>
    </figure>
  </chapter>
</book>
"""

PLAIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<book>
  <chapter>
    <figure>
      <figure-title>图七 铜鼎</figure-title>
      <figure-note>1. 铜鼎（M4:1）</figure-note>
      <mediaobject>
        <imageobject><imagedata fileref="media/fig7.png"/></imageobject>
      </mediaobject>
    </figure>
  </chapter>
</book>
"""

NESTED_AND_BROKEN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<book>
  <figure>
    <title>错位标题不得采用</title>
    <caption>
      <figure-title>嵌套标题不得采用</figure-title>
      <figure-note>嵌套图注不得采用</figure-note>
    </caption>
    <mediaobject>
      <imageobject><imagedata fileref="media/nested.png"/></imageobject>
    </mediaobject>
  </figure>
  <figure>
    <figure-title>无 imagedata 必须跳过</figure-title>
  </figure>
  <figure>
    <figure-title>空 fileref 必须跳过</figure-title>
    <mediaobject><imageobject><imagedata fileref="   "/></imageobject></mediaobject>
  </figure>
  <figure>
    <figure-title>缺 fileref 属性必须跳过</figure-title>
    <mediaobject><imageobject><imagedata/></imageobject></mediaobject>
  </figure>
  <figure>
    <mediaobject>
      <imageobject><imagedata fileref="media/no_caption.png"/></imageobject>
    </mediaobject>
  </figure>
</book>
"""


def _write_xml(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_book_namespaced_keeps_titles_notes_body_and_media(tmp_path):
    xml_path = _write_xml(tmp_path / "data.xml", NAMESPACED_XML)

    figures = parse_book(xml_path, "bookA")

    assert [f.figure_id for f in figures] == ["bookA:fig212", "bookA:fig213"]
    assert all(isinstance(f, FigureInput) for f in figures)
    assert {f.book_id for f in figures} == {"bookA"}

    first, second = figures
    assert first.caption == "图二一二 铜舟"
    # Multiple direct figure-note children are joined with a newline.
    assert first.figure_note == "1. 铜舟（M4：6）\n0 8厘米"
    assert [p["id"] for p in first.body_paras] == ["p1", "p2"]
    assert [p["text"] for p in first.body_paras] == ["正文一 强调。", "正文二"]
    # default media root is the XML directory; fileref is media-relative.
    assert Path(first.media_path).resolve() == (
        xml_path.parent / "media" / "fig212.png"
    ).resolve()
    assert Path(second.media_path).resolve() == (
        xml_path.parent / "media" / "sub" / "fig213.jpg"
    ).resolve()

    # A missing figure-note is None, never inferred from other text.
    assert second.caption == "图二一三 铁削"
    assert second.figure_note is None


def test_parse_book_namespaces_figure_id_by_book_id(tmp_path):
    xml_path = _write_xml(tmp_path / "data.xml", NAMESPACED_XML)

    figures = parse_book(xml_path, "另一本书")

    assert [f.figure_id for f in figures] == ["另一本书:fig212", "另一本书:fig213"]
    assert {f.book_id for f in figures} == {"另一本书"}


def test_parse_book_without_namespace(tmp_path):
    xml_path = _write_xml(tmp_path / "data.xml", PLAIN_XML)

    figures = parse_book(xml_path, "bookB")

    assert len(figures) == 1
    assert figures[0].figure_id == "bookB:fig7"
    assert figures[0].caption == "图七 铜鼎"
    assert figures[0].figure_note == "1. 铜鼎（M4:1）"


def test_parse_book_media_root_override_with_chinese_paths(tmp_path):
    book_dir = tmp_path / "中文 书"
    xml_path = _write_xml(book_dir / "data.xml", NAMESPACED_XML)
    media_root = tmp_path / "外部 媒体"

    figures = parse_book(xml_path, "bookC", media_root=media_root)

    assert Path(figures[0].media_path).resolve() == (
        media_root / "media" / "fig212.png"
    ).resolve()
    assert Path(figures[1].media_path).resolve() == (
        media_root / "media" / "sub" / "fig213.jpg"
    ).resolve()
    assert figures[0].figure_id == "bookC:fig212"


def test_parse_book_only_direct_children_and_skips_invalid_figures(tmp_path):
    xml_path = _write_xml(tmp_path / "data.xml", NESTED_AND_BROKEN_XML)

    figures = parse_book(xml_path, "bookD")

    # Three figures must be skipped: no imagedata, blank fileref, absent
    # fileref attribute.  The nested-title figure is kept but must not
    # borrow its grandchild title/note.
    assert [f.figure_id for f in figures] == ["bookD:nested", "bookD:no_caption"]
    nested, no_caption = figures
    assert nested.caption is None
    assert nested.figure_note is None
    assert no_caption.caption is None
    assert no_caption.figure_note is None
    assert nested.body_paras == []


def test_negative_control_figures_without_media_never_appear(tmp_path):
    """A figure node alone is not a figure input; media is mandatory."""
    xml_path = _write_xml(tmp_path / "data.xml", NESTED_AND_BROKEN_XML)

    figures = parse_book(xml_path, "bookD")

    # Only the two media-backed figures survive; the three caption-only
    # figures (missing/blank/attr-less fileref) must not be emitted.
    assert [f.fileref for f in figures] == ["media/nested.png", "media/no_caption.png"]
    assert len(figures) == 2
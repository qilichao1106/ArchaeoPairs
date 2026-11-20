"""Namespace-agnostic DocBook XML ingestion (R-IN-01..05).

Parses ``books/<book>/data.xml`` into :class:`FigureInput` objects. Matching is
by local tag name only, so namespaced and un-namespaced DocBook both work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator
from xml.etree import ElementTree as ET

from archaeopairs.models import FigureInput

_TITLE_TAG = "figure-title"
_NOTE_TAG = "figure-note"
_IMAGEDATA_TAG = "imagedata"
_PARA_TAG = "para"


def _localname(tag: object) -> str:
    """Return the local tag name, stripping any ``{namespace}`` prefix."""
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _iter_elements(root: ET.Element, name: str) -> Iterator[ET.Element]:
    for el in root.iter():
        if _localname(el.tag) == name:
            yield el


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _direct_child(el: ET.Element, name: str) -> ET.Element | None:
    for child in el:
        if _localname(child.tag) == name:
            return child
    return None


def _direct_children(el: ET.Element, name: str) -> Iterable[ET.Element]:
    for child in el:
        if _localname(child.tag) == name:
            yield child


def _figure_note(figure: ET.Element) -> str | None:
    notes = [
        text
        for text in (_text(child) for child in _direct_children(figure, _NOTE_TAG))
        if text
    ]
    if not notes:
        return None
    return "\n".join(notes)


def _figure_fileref(figure: ET.Element) -> str | None:
    imagedata = next(_iter_elements(figure, _IMAGEDATA_TAG), None)
    if imagedata is None:
        return None
    fileref = imagedata.get("fileref")
    if fileref is None:
        return None
    fileref = fileref.strip()
    return fileref or None


def _collect_body_paras(root: ET.Element) -> list[dict]:
    # Only non-empty paragraphs are kept; ids are ``p1``..``pN`` over the kept
    # sequence so numbering stays contiguous (no gaps from blank paragraphs).
    paras: list[dict] = []
    for para in _iter_elements(root, _PARA_TAG):
        text = _text(para)
        if not text:
            continue
        paras.append({"id": f"p{len(paras) + 1}", "text": text})
    return paras


def _resolve_media_path(media_root: Path, fileref: str) -> str:
    # ``fileref`` is a media-relative path (R-IN-01); join with ``/`` semantics
    # then let the OS normalize. ``.resolve()`` keeps Windows Chinese paths and
    # makes the result absolute for downstream consumers.
    return str((media_root / fileref).resolve())


def parse_book(
    xml_path: str | Path,
    book_id: str,
    media_root: str | Path | None = None,
) -> list[FigureInput]:
    """Parse a DocBook XML file into a list of :class:`FigureInput`.

    - Namespace-agnostic: matching is on local tag names.
    - ``figure-title`` / ``figure-note`` are read only as *direct* children of
      ``figure``; multiple notes are joined with newlines.
    - Figures without an ``imagedata@fileref`` are skipped (R-IN-05).
    - ``media_path`` = ``media_root / fileref``; defaults to the XML directory.
    - ``figure_id`` = ``"{book_id}:{stem(fileref)}"``.
    - ``body_paras`` collects every non-empty ``para`` text, numbered p1..pN.
    """

    xml_path = Path(xml_path)
    if media_root is None:
        media_root = xml_path.parent
    else:
        media_root = Path(media_root)

    tree = ET.parse(str(xml_path))
    root = tree.getroot()

    body_paras = _collect_body_paras(root)

    figures: list[FigureInput] = []
    for figure in _iter_elements(root, "figure"):
        fileref = _figure_fileref(figure)
        if not fileref:
            continue
        title = _text(_direct_child(figure, _TITLE_TAG)) or None
        note = _figure_note(figure)
        figure_id = f"{book_id}:{Path(fileref).stem}"
        figures.append(
            FigureInput(
                book_id=book_id,
                figure_id=figure_id,
                fileref=fileref,
                media_path=_resolve_media_path(media_root, fileref),
                caption=title,
                figure_note=note,
                body_paras=body_paras,
            )
        )
    return figures

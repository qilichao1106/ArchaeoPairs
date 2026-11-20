"""Synthetic images, scripted OCR providers and builders for frozen T-013 tests.

Nothing here reads ``books/``, loads a model or opens a socket.  ``ScriptedOCR``
scripts ``read_scales`` / ``read_glyphs`` replies and records every call, so the
L1 tests can assert which reader the pipeline used.  A script that runs out
raises: that freezes "exactly once" / "exactly twice" retry counts.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from archaeopairs.models import (
    FigureInput,
    OcrResult,
    ScaleBar,
    SeqLabel,
    TextBlock,
    View,
)

# Two drawings plus two printed digit glyphs, each nearest to its own drawing.
L1_BOXES = [(100, 20, 180, 90), (230, 20, 300, 90)]
L1_GLYPHS = [(55, 30, 73, 48), (252, 100, 270, 118)]
L1_CAPTION = "图一 出土器物"
L1_NOTE = "1. 陶鼎（M1:1） 2. 陶盒（M1:2）"


def line_image(path, *, size=(320, 200), boxes=(), glyphs=(), bar=None):
    """White RGB canvas with black drawings/glyphs and an optional bar."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for box in (*boxes, *glyphs):
        draw.rectangle(tuple(int(v) for v in box), fill="black")
    if bar is not None:
        draw.rectangle(tuple(int(v) for v in bar), fill="black")
    image.save(path)
    return Path(path)


def view(view_id, bbox):
    box = tuple(int(v) for v in bbox)
    area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
    return View(view_id=view_id, bbox=box, area=area, mask_rle="")


def seq_label(text, bbox):
    return SeqLabel(text=text, bbox=tuple(int(v) for v in bbox), conf=0.99)


def scale_bar(text, bbox, *, prefix_nos=(), value=4.0, unit="厘米"):
    return ScaleBar(
        text=text,
        bbox=tuple(int(v) for v in bbox),
        value=value,
        unit=unit,
        prefix_nos=[str(v) for v in prefix_nos],
    )


def text_block(text, bbox):
    return TextBlock(text=text, bbox=tuple(int(v) for v in bbox))


def ocr_result(*, seqs=(), scales=(), texts=(), source="fake"):
    return OcrResult(
        seqs=list(seqs), scales=list(scales), texts=list(texts), source=source
    )


def para(pid, text):
    return {"id": pid, "text": text}


def figure(path, *, caption=L1_CAPTION, note=L1_NOTE, body=None):
    return FigureInput(
        book_id="bookA",
        figure_id="fig1",
        fileref=Path(path).name,
        media_path=str(path),
        caption=caption,
        figure_note=note,
        body_paras=list(body or []),
    )


def l1_figure(tmp_path, name="l1.png"):
    """The shared L1 fixture: two drawings, two glyphs, note/body text."""
    path = line_image(tmp_path / name, boxes=L1_BOXES, glyphs=L1_GLYPHS)
    fig = figure(
        path,
        body=[
            para("p1", "陶鼎标本M1:1，泥质灰陶。"),
            para("p2", "陶盒标本M1:2，泥质灰陶。"),
        ],
    )
    return str(path), fig


def shared_scale(text="0 4厘米", bbox=(35, 175, 305, 190)):
    """One bar naming both seqs, so L1 can bind it by prefix."""
    return scale_bar(text, bbox, prefix_nos=["1", "2"])


def glyph_seq_labels():
    """Whole-image seq boxes at the printed glyph positions (full-read shape)."""
    return [seq_label("1", (55, 30, 73, 48)), seq_label("2", (252, 100, 270, 118))]


class PlainOCR:
    """Provider with only ``read`` (the frozen T-010 surface)."""

    def __init__(self, result=None, *, error=None):
        self.result = result if result is not None else OcrResult()
        self.error = error
        self.read_calls = []

    def read(self, image_path):
        self.read_calls.append(str(image_path))
        if self.error is not None:
            raise self.error
        return self.result


class ScriptedOCR(PlainOCR):
    """Provider with the optional readers; scripted and call-recording."""

    def __init__(
        self,
        *,
        scale_results=(),
        glyphs=None,
        glyph_error=None,
        read_result=None,
        read_error=None,
    ):
        super().__init__(read_result, error=read_error)
        self.scale_results = list(scale_results)
        self.glyphs = glyphs
        self.glyph_error = glyph_error
        self.scale_calls = []
        self.glyph_calls = []

    def read_scales(self, image_path):
        self.scale_calls.append(str(image_path))
        if not self.scale_results:
            raise AssertionError("read_scales called more often than scripted")
        item = self.scale_results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def read_glyphs(self, image_path, boxes):
        self.glyph_calls.append(
            (str(image_path), [tuple(int(v) for v in box) for box in boxes])
        )
        if self.glyph_error is not None:
            raise self.glyph_error
        return list(self.glyphs or [])


class FakeWriter:
    """In-memory writer recording images, pairs and ledger rows."""

    def __init__(self):
        self.images: list[tuple[str, tuple[int, ...]]] = []
        self.pairs: list[dict] = []
        self.ledger: list[dict] = []
        self.write_pairs_calls = 0
        self.write_ledger_calls = 0

    def write_image(self, name, image):
        self.images.append((name, tuple(int(v) for v in np.asarray(image).shape)))
        return name

    def write_pairs(self, records):
        self.write_pairs_calls += 1
        self.pairs.extend(records)

    def write_ledger(self, rows):
        self.write_ledger_calls += 1
        self.ledger.extend(rows)


def stage_payload(ledger: list[dict], kind: str):
    """Payload of the single stage entry with ``kind`` (e.g. ``ocr``)."""
    entries = [row for row in ledger if row.get("kind") == kind]
    assert len(entries) == 1, (kind, entries)
    return entries[0]["payload"]
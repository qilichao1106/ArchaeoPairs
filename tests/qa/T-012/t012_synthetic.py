"""Synthetic images, fake OCR/glyph readers and builders for frozen T-012 tests.

Nothing here touches ``books/`` or the network.  Line drawings are white PIL
canvases with black filled boxes (a print-like bar is its own rectangle); colour
plates are seeded RGB noise.  ``FakeOCR`` returns a pre-built ``OcrResult`` and
can add the optional T-011 ``read_glyphs`` method.
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

_IMG_DEFAULT = (300, 200)


def line_image(
    path,
    *,
    size=_IMG_DEFAULT,
    boxes=(),
    glyphs=(),
    texts=(),
    bar=None,
):
    """White RGB canvas with black boxes, glyph-like blocks and a bar."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for box in (*boxes, *glyphs, *texts):
        draw.rectangle(tuple(int(value) for value in box), fill="black")
    if bar is not None:
        draw.rectangle(tuple(int(value) for value in bar), fill="black")
    image.save(path)
    return Path(path)


def color_image(path, *, size=(160, 120), seed=20261201):
    """Seeded RGB noise: the classifier sees a colour plate, not a line drawing."""
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(array, mode="RGB").save(path)
    return Path(path)


def view(view_id: int, bbox) -> View:
    box = tuple(int(value) for value in bbox)
    area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
    return View(view_id=view_id, bbox=box, area=area, mask_rle="")


def seq_label(text: str, bbox) -> SeqLabel:
    return SeqLabel(text=text, bbox=tuple(int(value) for value in bbox), conf=0.99)


def scale_bar(text: str, bbox, *, prefix_nos=(), value: float = 4.0,
              unit: str = "厘米") -> ScaleBar:
    return ScaleBar(
        text=text,
        bbox=tuple(int(value) for value in bbox),
        value=value,
        unit=unit,
        prefix_nos=[str(item) for item in prefix_nos],
    )


def text_block(text: str, bbox) -> TextBlock:
    return TextBlock(text=text, bbox=tuple(int(value) for value in bbox))


def ocr_result(*, seqs=(), scales=(), texts=(), source: str = "fake") -> OcrResult:
    return OcrResult(
        seqs=list(seqs), scales=list(scales), texts=list(texts), source=source
    )


def para(pid: str, text: str) -> dict:
    return {"id": pid, "text": text}


def figure(
    path,
    *,
    caption: str | None = None,
    note: str | None = None,
    body=(),
    book_id: str = "bookA",
    figure_id: str = "fig1",
    fileref: str | None = None,
) -> FigureInput:
    return FigureInput(
        book_id=book_id,
        figure_id=figure_id,
        fileref=fileref or Path(path).name,
        media_path=str(path),
        caption=caption,
        figure_note=note,
        body_paras=list(body),
    )


class PlainOCR:
    """OCR provider without the optional ``read_glyphs`` capability."""

    def __init__(self, result: OcrResult):
        self.result = result
        self.calls: list[str] = []

    def read(self, image_path):
        self.calls.append(str(image_path))
        return self.result


class FakeOCR(PlainOCR):
    """Fixed OCR plus a scripted ``read_glyphs`` reply; records both calls."""

    def __init__(
        self,
        result: OcrResult | None = None,
        *,
        glyphs=None,
        glyph_error: BaseException | None = None,
    ):
        super().__init__(result if result is not None else OcrResult())
        self.glyphs = glyphs
        self.glyph_error = glyph_error
        self.glyph_calls: list[tuple[str, list[tuple]]] = []

    def read_glyphs(self, image_path, boxes):
        self.glyph_calls.append(
            (str(image_path), [tuple(int(v) for v in box) for box in boxes])
        )
        if self.glyph_error is not None:
            raise self.glyph_error
        return list(self.glyphs or [])


class FakeClient:
    """Offline VLM client returning one fixed reply and recording prompts."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[tuple[str, str, bool]] = []

    def describe_image(self, image_path, prompt, json_mode=False):
        self.calls.append((str(image_path), prompt, bool(json_mode)))
        return self.reply


def fake_client(reply: str) -> FakeClient:
    return FakeClient(reply)


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
    """Payload of the single stage entry with ``kind`` (e.g. ``views``)."""
    entries = [row for row in ledger if row.get("kind") == kind]
    assert len(entries) == 1, (kind, entries)
    return entries[0]["payload"]
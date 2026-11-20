"""Synthetic images, fake OCR/writer and figure builders for the frozen T-010 tests.

Nothing here touches ``books/`` or the network.  Line drawings are white PIL
canvases with black filled regions (no anti-aliasing); colour plates are seeded
random RGB noise, which the classifier reads as ``color``.  Fake OCR returns a
pre-built :class:`OcrResult` and records every call; the fake writer records
what the pipeline hands it and can raise on demand to exercise fail-closed
paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from archaeopairs.models import (
    FigureInput,
    OcrResult,
    ScaleBar,
    SeqLabel,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAIR_SCHEMA = _REPO_ROOT / "contracts" / "pair_record.schema.json"


# --- image builders --------------------------------------------------------


def line_image(
    path,
    *,
    size: tuple[int, int] = (300, 200),
    boxes=(),
    glyphs=(),
    bar=None,
) -> Path:
    """White RGB canvas with black filled boxes, optional glyphs and a scale bar."""
    width, height = size
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for box in (*boxes, *glyphs):
        draw.rectangle(tuple(int(value) for value in box), fill="black")
    if bar is not None:
        draw.rectangle(tuple(int(value) for value in bar), fill="black")
    image.save(path)
    return Path(path)


def color_image(path, *, size: tuple[int, int] = (160, 120), seed: int = 20261121) -> Path:
    """Seeded RGB noise: the classifier sees a colour plate, not a line drawing."""
    width, height = size
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    Image.fromarray(array, mode="RGB").save(path)
    return Path(path)


def blank_image(path, *, size: tuple[int, int] = (300, 200)) -> Path:
    """Pure white canvas: ``segment_views`` returns no views."""
    width, height = size
    Image.new("RGB", (width, height), "white").save(path)
    return Path(path)


# --- OCR / figure builders -------------------------------------------------


def seq_label(text: str, bbox) -> SeqLabel:
    return SeqLabel(text=text, bbox=tuple(int(value) for value in bbox), conf=0.99)


def scale_bar(text: str, bbox, *, prefix_nos=(), value: float = 5.0, unit: str = "cm") -> ScaleBar:
    return ScaleBar(
        text=text,
        bbox=tuple(int(value) for value in bbox),
        value=value,
        unit=unit,
        prefix_nos=[str(item) for item in prefix_nos],
    )


def ocr_result(*, seqs=(), scales=(), source: str = "fake") -> OcrResult:
    return OcrResult(seqs=list(seqs), scales=list(scales), source=source)


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


# --- fakes -----------------------------------------------------------------


class FakeOCR:
    """Returns one pre-built ``OcrResult``; optionally raises and records calls."""

    def __init__(self, result: OcrResult | None = None, error: BaseException | None = None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def read(self, image_path):
        self.calls.append(str(image_path))
        if self.error is not None:
            raise self.error
        return self.result


class FakeWriter:
    """In-memory writer that records images/pairs/ledger and can fail on demand."""

    def __init__(
        self,
        *,
        fail_image: BaseException | None = None,
        fail_name_prefix: str | None = None,
        fail_pairs: BaseException | None = None,
        fail_ledger: BaseException | None = None,
    ):
        self.fail_image = fail_image
        self.fail_name_prefix = fail_name_prefix
        self.fail_pairs = fail_pairs
        self.fail_ledger = fail_ledger
        self.images: list[tuple[str, tuple[int, ...]]] = []
        self.pairs: list[dict] = []
        self.ledger: list[dict] = []
        self.write_pairs_calls = 0
        self.write_ledger_calls = 0

    def write_image(self, name, image):
        if self.fail_image is not None:
            raise self.fail_image
        if self.fail_name_prefix and str(name).startswith(self.fail_name_prefix):
            raise OSError(f"writer refused {name}")
        self.images.append((name, tuple(int(value) for value in np.asarray(image).shape)))
        return name

    def write_pairs(self, records):
        self.write_pairs_calls += 1
        if self.fail_pairs is not None:
            raise self.fail_pairs
        self.pairs.extend(records)

    def write_ledger(self, rows):
        self.write_ledger_calls += 1
        if self.fail_ledger is not None:
            raise self.fail_ledger
        self.ledger.extend(rows)


# --- contract helper -------------------------------------------------------


def validate_pair(pair) -> None:
    """Assert one emitted PairRecord validates against the frozen schema."""
    from jsonschema import Draft202012Validator

    schema = json.loads(_PAIR_SCHEMA.read_text(encoding="utf-8"))
    instance = pair.model_dump(mode="json")
    errors = list(Draft202012Validator(schema).iter_errors(instance))
    assert errors == [], [error.message for error in errors]


def pair_rows(ledger: list[dict]) -> list[dict]:
    """Ledger rows belonging to a Pair (stage entries carry ``kind``)."""
    return [row for row in ledger if "artifact_id" in row and "kind" not in row]
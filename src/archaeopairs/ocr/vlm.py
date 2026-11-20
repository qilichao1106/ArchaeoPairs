"""VLM-backed structured OCR provider (T-004, AC-03).

The model is asked for strict JSON; anything that cannot be interpreted as a
well-formed :class:`OcrResult` raises :class:`OcrError` rather than silently
degrading to an empty result.  A valid "no text in this image" reply is still
a legal empty :class:`OcrResult`.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from pydantic import ValidationError

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr.base import OCRProvider
from archaeopairs.vlm.client import VlmClient
from archaeopairs.vlm.prompts import GLYPH_PROMPT, OCR_PROMPT, SCALE_PROMPT

__all__ = ["OcrError", "VlmOCRProvider"]

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class OcrError(RuntimeError):
    """The VLM reply could not be turned into a valid :class:`OcrResult`."""


def _load_payload(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating a Markdown fence or surrounding prose."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
    except ValueError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise OcrError("VLM OCR reply is not valid JSON") from None
        try:
            payload = json.loads(candidate[start : end + 1])
        except ValueError as exc:
            raise OcrError("VLM OCR reply is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OcrError("VLM OCR reply must be a JSON object")
    return payload


def _bbox(value: Any, path: str) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise OcrError(f"{path}.bbox must be a 4-element list")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise OcrError(f"{path}.bbox must contain only numbers")
    box = tuple(int(round(v)) for v in value)
    if box[0] > box[2] or box[1] > box[3]:
        raise OcrError(f"{path}.bbox must satisfy x0<=x1 and y0<=y1")
    return box  # type: ignore[return-value]


def _items(payload: dict[str, Any], key: str) -> list[Any]:
    items = payload.get(key, [])
    if items is None:
        return []
    if not isinstance(items, list):
        raise OcrError(f"{key} must be a list")
    return items


def _obj(item: Any, path: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OcrError(f"{path} must be an object")
    return item


def _text(item: dict[str, Any], path: str) -> str:
    value = item.get("text")
    if not isinstance(value, str):
        raise OcrError(f"{path}.text is required and must be a string")
    return value


def _opt_float(value: Any, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OcrError(f"{path} must be a number or null")
    return float(value)


def _opt_str(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OcrError(f"{path} must be a string or null")
    return value


def _parse_seqs(payload: dict[str, Any]) -> list[SeqLabel]:
    out = []
    for i, raw in enumerate(_items(payload, "seqs")):
        path = f"seqs[{i}]"
        item = _obj(raw, path)
        try:
            out.append(
                SeqLabel(
                    text=_text(item, path),
                    bbox=_bbox(item.get("bbox"), path),
                    conf=_opt_float(item.get("conf"), f"{path}.conf"),
                )
            )
        except ValidationError as exc:
            raise OcrError(f"{path} is invalid: {exc}") from exc
    return out


def _parse_scales(payload: dict[str, Any]) -> list[ScaleBar]:
    out = []
    for i, raw in enumerate(_items(payload, "scales")):
        path = f"scales[{i}]"
        item = _obj(raw, path)
        prefix_nos = item.get("prefix_nos", [])
        if prefix_nos is None:
            prefix_nos = []
        if not isinstance(prefix_nos, list) or any(
            not isinstance(v, str) for v in prefix_nos
        ):
            raise OcrError(f"{path}.prefix_nos must be a list of strings")
        try:
            out.append(
                ScaleBar(
                    text=_text(item, path),
                    bbox=_bbox(item.get("bbox"), path),
                    value=_opt_float(item.get("value"), f"{path}.value"),
                    unit=_opt_str(item.get("unit"), f"{path}.unit"),
                    prefix_nos=list(prefix_nos),
                )
            )
        except ValidationError as exc:
            raise OcrError(f"{path} is invalid: {exc}") from exc
    return out


def _parse_texts(payload: dict[str, Any]) -> list[TextBlock]:
    out = []
    for i, raw in enumerate(_items(payload, "texts")):
        path = f"texts[{i}]"
        item = _obj(raw, path)
        try:
            out.append(TextBlock(text=_text(item, path), bbox=_bbox(item.get("bbox"), path)))
        except ValidationError as exc:
            raise OcrError(f"{path} is invalid: {exc}") from exc
    return out


def parse_ocr_payload(payload: dict[str, Any]) -> OcrResult:
    """Validate a decoded OCR JSON object into an ``OcrResult(source="vlm")``."""
    return OcrResult(
        seqs=_parse_seqs(payload),
        scales=_parse_scales(payload),
        texts=_parse_texts(payload),
        source="vlm",
        raw=payload,
    )


_GLYPH_CELL = 128
_GLYPH_COLUMNS = 4
_GLYPH_TARGET = 72


def build_glyph_grid(image_path: str | Path, boxes: list[tuple]) -> Image.Image:
    """Tile glyph crops in reading order so one VLM call reads all digits.

    Whole-image coordinate detection drifts; segmentation already gives exact
    glyph boxes, so only the character value is asked from the model.  Crops
    are enlarged with NEAREST (LANCZOS blurs these low-res scans and changes
    digits such as 5 into 7) and laid on a regular grid, one cell per box.
    """
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    columns = _GLYPH_COLUMNS
    rows = max(1, (len(boxes) + columns - 1) // columns)
    canvas = Image.new("RGB", (columns * _GLYPH_CELL, rows * _GLYPH_CELL), "white")
    draw = ImageDraw.Draw(canvas)
    for index, box in enumerate(boxes):
        x0, y0, x1, y1 = (int(v) for v in box)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(image.width, x1), min(image.height, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = image.crop((x0, y0, x1, y1))
        scale = max(1, min(8, round(_GLYPH_TARGET / max(1, crop.height))))
        crop = crop.resize((crop.width * scale, crop.height * scale), Image.NEAREST)
        crop.thumbnail((_GLYPH_CELL - 8, _GLYPH_CELL - 8), Image.NEAREST)
        left = (index % columns) * _GLYPH_CELL + (_GLYPH_CELL - crop.width) // 2
        top = (index // columns) * _GLYPH_CELL + (_GLYPH_CELL - crop.height) // 2
        canvas.paste(crop, (left, top))
        draw.rectangle(
            [(index % columns) * _GLYPH_CELL, (index // columns) * _GLYPH_CELL,
             (index % columns + 1) * _GLYPH_CELL - 1,
             (index // columns + 1) * _GLYPH_CELL - 1],
            outline=(190, 190, 190),
        )
    return canvas


def _parse_glyph_payload(reply: str, count: int) -> list[str | None]:
    payload = _load_payload(reply)
    items = payload.get("glyphs")
    if not isinstance(items, list):
        raise OcrError("VLM glyph reply must contain a glyphs array")
    values: list[str | None] = []
    for item in items[:count]:
        if item is None:
            values.append(None)
        elif isinstance(item, str):
            values.append(item.strip() or None)
        else:
            values.append(str(item))
    values.extend([None] * (count - len(values)))
    return values


class VlmOCRProvider(OCRProvider):
    """Read one image with the VLM and return strict structured OCR."""

    def __init__(self, client: VlmClient) -> None:
        self.client = client

    def read(self, image_path: str | Path) -> OcrResult:
        try:
            reply = self.client.describe_image(
                image_path, OCR_PROMPT, json_mode=True
            )
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(f"VLM OCR request failed: {type(exc).__name__}") from exc
        if not isinstance(reply, str):
            raise OcrError("VLM OCR reply content is not text")
        try:
            return parse_ocr_payload(_load_payload(reply))
        except OcrError:
            raise
        except Exception as exc:  # defensive: never leak a partial result
            raise OcrError(f"VLM OCR reply is unusable: {type(exc).__name__}") from exc

    def _describe(self, image_path: str | Path, prompt: str) -> str:
        """One-shot describe for optional calls (no malformed-JSON retries)."""
        try:
            return self.client.describe_image(
                image_path, prompt, json_mode=True, max_retries=0)
        except TypeError:  # lightweight fake clients without the kwarg
            return self.client.describe_image(
                image_path, prompt, json_mode=True)

    def read_scales(self, image_path: str | Path) -> OcrResult:
        """Read only scales/text; seq digits come from the glyph grid."""
        try:
            reply = self._describe(image_path, SCALE_PROMPT)
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(
                f"VLM scale OCR request failed: {type(exc).__name__}") from exc
        if not isinstance(reply, str):
            raise OcrError("VLM scale reply content is not text")
        try:
            payload = _load_payload(reply)
            return OcrResult(
                seqs=[],
                scales=_parse_scales(payload),
                texts=_parse_texts(payload),
                source="vlm",
                raw=payload,
            )
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(
                f"VLM scale reply is unusable: {type(exc).__name__}") from exc

    def read_glyphs(self, image_path: str | Path,
                    boxes: list[tuple]) -> list[str | None]:
        """Read the character in each segmented glyph box, in order."""
        boxes = list(boxes or [])
        if not boxes:
            return []
        try:
            grid = build_glyph_grid(image_path, boxes)
        except Exception as exc:
            raise OcrError(
                f"cannot build glyph grid: {type(exc).__name__}") from exc
        with tempfile.TemporaryDirectory(prefix="archaeopairs_glyphs_") as tmp:
            grid_path = Path(tmp) / "glyphs.png"
            grid.save(grid_path)
            try:
                reply = self._describe(
                    grid_path, GLYPH_PROMPT.format(count=len(boxes)))
            except OcrError:
                raise
            except Exception as exc:
                raise OcrError(
                    f"VLM glyph request failed: {type(exc).__name__}") from exc
        if not isinstance(reply, str):
            raise OcrError("VLM glyph reply content is not text")
        try:
            return _parse_glyph_payload(reply, len(boxes))
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(
                f"VLM glyph reply is unusable: {type(exc).__name__}") from exc

"""VLM-backed structured OCR provider (T-004, AC-03).

The model is asked for strict JSON; anything that cannot be interpreted as a
well-formed :class:`OcrResult` raises :class:`OcrError` rather than silently
degrading to an empty result.  A valid "no text in this image" reply is still
a legal empty :class:`OcrResult`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr.base import OCRProvider
from archaeopairs.vlm.client import VlmClient
from archaeopairs.vlm.prompts import OCR_PROMPT

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

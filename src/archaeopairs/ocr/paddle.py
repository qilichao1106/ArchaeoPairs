"""PaddleOCR-backed structured OCR provider (T-005, AC-03).

The Paddle engine is injected in tests and loaded lazily in production: the
``paddleocr`` import and ``PaddleOCR(...)`` construction only happen on the
first :meth:`PaddleOCRProvider.read` when no engine was given.  A broken
install raises :class:`PaddleUnavailableError` (never a silent empty result),
while an engine that fails mid-read raises :class:`OcrError`.

Both PaddleOCR 3.x (``engine.predict`` -> ``rec_texts`` / ``rec_scores`` /
``rec_polys`` | ``dt_polys``, or a ``.json`` dict with the same keys) and the
legacy ``engine.ocr`` output (``[[box, (text, score)], ...]``, possibly nested
per image) are normalised.  Every box becomes an axis-aligned
``[x0, y0, x1, y1]`` in image pixels; a 4-point polygon is reduced to min/max.
Each line is then classified as a sequence label, a scale-bar reading, or a
plain text block.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from archaeopairs.models import BBox, OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr.base import OCRProvider
from archaeopairs.ocr.vlm import OcrError

__all__ = ["PaddleOCRProvider", "PaddleUnavailableError"]

# Pure sequence/ordinal label: "1", "12", "2-1", "3.4", "(5)", "⑥".
_SEQ = re.compile(
    r"^[(\[{（【]?\s*(?:\d{1,4}|[一二三四五六七八九十]{1,4})"
    r"(?:\s*[-–—./．、]\s*\d{1,4})?\s*[)\]）】]?\.?$"
)
# A number, literal separators, and a metric length unit.
_SCALE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>厘米|公分|毫米|cm|mm)", re.IGNORECASE
)
# 0.5 <= value < 1000 makes the unqualified "mm"/"cm" suffix a real scale bar.
_UNIT_MAX = 1000.0


class PaddleUnavailableError(OcrError):
    """The PaddleOCR package is missing or the engine failed to initialise."""


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _number(value: Any) -> float:
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OcrError("paddle bbox coordinate is not numeric")
    return float(value)


def _px(value: float) -> int:
    """Round a pixel coordinate half-up (``int`` truncation is not enough)."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _bbox(poly: Any) -> BBox:
    """Reduce a 4-point polygon / box to axis-aligned ``[x0, y0, x1, y1]``."""
    if poly is None:
        return (0, 0, 0, 0)
    if hasattr(poly, "tolist"):  # numpy array
        poly = poly.tolist()
    if not isinstance(poly, (list, tuple)):
        raise OcrError(f"paddle bbox is not a coordinate list: {type(poly).__name__}")
    if len(poly) == 4 and all(
        not isinstance(v, (list, tuple)) and not hasattr(v, "tolist") for v in poly
    ):
        # Flat axis-aligned box ``[x0, y0, x1, y1]``.
        return (_px(_number(poly[0])), _px(_number(poly[1])),
                _px(_number(poly[2])), _px(_number(poly[3])))
    if len(poly) == 8 and all(
        not isinstance(v, (list, tuple)) and not hasattr(v, "tolist") for v in poly
    ):
        # Flat four-point polygon ``[x0,y0, x1,y1, x2,y2, x3,y3]``.
        poly = [[poly[i], poly[i + 1]] for i in range(0, 8, 2)]
    rows: list[Any] = list(poly)
    xs: list[float] = []
    ys: list[float] = []
    for point in rows:
        if hasattr(point, "tolist"):
            point = point.tolist()
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise OcrError("paddle bbox contains a malformed point")
        xs.append(_number(point[0]))
        ys.append(_number(point[1]))
    return (_px(min(xs)), _px(min(ys)), _px(max(xs)), _px(max(ys)))

def _score(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _lines_from_dict(payload: Mapping[str, Any]) -> list[tuple[str, Any, Any]] | None:
    """Normalise a 3.x result dict; ``None`` when it is not a text-result dict."""
    if "rec_texts" not in payload:
        return None
    texts = payload.get("rec_texts") or []
    scores = payload.get("rec_scores") or []
    polys = payload.get("rec_polys")
    if polys is None:
        polys = payload.get("dt_polys")
    polys = [] if polys is None else polys
    if not (len(texts) == len(scores) == len(polys)):
        raise OcrError(
            "paddle result has mismatched rec_texts/rec_scores/rec_polys lengths"
        )
    return list(zip(texts, scores, polys))


def _is_legacy_line(node: Any) -> bool:
    """True for a top-level legacy line ``[box, (text, score)]``.

    Guarded so a bare ``(text, score)`` or a genuine list of lines (whose
    second item is another list) is not mistaken for a single line.
    """
    if not isinstance(node, (list, tuple)) or len(node) != 2:
        return False
    box, pair = node
    if hasattr(box, "tolist"):  # numpy array box, same as _bbox
        box = box.tolist()
    if not isinstance(box, (list, tuple)) or not isinstance(pair, (list, tuple)):
        return False
    flat = len(box) in (4, 8) and all(
        not isinstance(v, (list, tuple)) and not hasattr(v, "tolist") for v in box
    )
    quad = len(box) == 4 and all(
        isinstance(v, (list, tuple)) or hasattr(v, "tolist") for v in box
    )
    if not (flat or quad):
        return False
    return len(pair) in (1, 2) and isinstance(pair[0], str)


def _iter_legacy(node: Any) -> Iterable[tuple[str, Any, Any]]:
    """Flatten legacy ``[[box, (text, score)], ...]`` (possibly nested)."""
    while isinstance(node, (list, tuple)) and len(node) == 1:
        node = node[0]
    if not isinstance(node, (list, tuple)):
        return
    if len(node) == 2 and isinstance(node[0], str):  # a single (text, score)
        yield node[0], node[1], None
        return
    if _is_legacy_line(node):  # a single top-level [box, (text, score)]
        yield node[1][0], node[1][1] if len(node[1]) > 1 else None, node[0]
        return
    for item in node:
        if item is None:
            continue
        if not isinstance(item, (list, tuple)):
            yield _coerce_text(item), None, None
        elif len(item) == 2 and isinstance(item[1], (list, tuple)) and item[1]:
            text, score = item[1][0], item[1][1] if len(item[1]) > 1 else None
            yield _coerce_text(text), score, item[0]
        elif len(item) == 3 and isinstance(item[0], str):
            yield item[0], item[1], item[2]
        else:
            yield from _iter_legacy(item)

def _unwrap(node: Any) -> Any:
    """Strip a ``.json`` result wrapper down to its data payload."""
    if hasattr(node, "json"):  # 3.x result object
        try:
            node = node.json
        except Exception as exc:
            raise OcrError(f"paddle result is unreadable: {type(exc).__name__}") from exc
        if callable(node):
            raise OcrError("paddle result .json is not a property")
        while isinstance(node, (list, tuple)) and len(node) == 1:
            node = node[0]
    return node


def _from_data(data: Any) -> list[tuple[str, Any, Any]]:
    if isinstance(data, Mapping):
        return _from_mapping(data)
    return list(_iter_legacy(data))


def _from_mapping(mapping: Mapping[str, Any]) -> list[tuple[str, Any, Any]]:
    lines = _lines_from_dict(mapping)
    if lines is not None:
        return lines
    for key in ("res", "result", "ocr_res"):
        if key in mapping:
            return _from_data(_unwrap(mapping[key]))
    if "rec_texts" in mapping:
        raise OcrError("paddle result has an empty or partial rec_texts group")
    rows: list[tuple[str, Any, Any]] = []
    for value in mapping.values():
        if isinstance(value, (Mapping, list, tuple)) or hasattr(value, "json"):
            rows.extend(_from_data(_unwrap(value)))
    return rows


def extract_lines(output: Any) -> list[tuple[str, Any, Any]]:
    """Turn any supported PaddleOCR output into ``(text, score, bbox)`` rows."""
    if output is None:
        return []
    node = _unwrap(output)
    while isinstance(node, (list, tuple)) and len(node) == 1:
        node = _unwrap(node[0])
    return _from_data(node)

def classify_line(text: str) -> tuple[str, float | None, str | None]:
    """Classify one OCR line as ``seq`` / ``scale`` / ``text``."""
    stripped = re.sub(r"\s+", " ", text).strip()
    if _SEQ.match(stripped):
        return "seq", None, None
    match = _SCALE.search(stripped)
    if match:
        unit = match.group("unit").lower()
        value = float(match.group("num"))
        if 0.0 < value < _UNIT_MAX:
            if unit in ("cm", "公分"):
                unit = "厘米"
            elif unit == "mm":
                unit = "毫米"
            return "scale", value, unit
    return "text", None, None


def _build_result(rows: Iterable[tuple[str, Any, Any]]) -> OcrResult:
    seqs: list[SeqLabel] = []
    scales: list[ScaleBar] = []
    texts: list[TextBlock] = []
    kept: list[dict[str, Any]] = []
    for text, score, box in rows:
        if not text.strip():
            continue
        bbox = _bbox(box)
        kind, value, unit = classify_line(text)
        conf = _score(score)
        if kind == "seq":
            seqs.append(SeqLabel(text=text.strip(), bbox=bbox, conf=conf))
        elif kind == "scale":
            scales.append(ScaleBar(text=text.strip(), bbox=bbox, value=value, unit=unit))
        else:
            texts.append(TextBlock(text=text.strip(), bbox=bbox))
        kept.append({"text": text, "bbox": list(bbox), "kind": kind, "conf": conf})
    return OcrResult(
        seqs=seqs,
        scales=scales,
        texts=texts,
        source="paddle",
        raw={"lines": kept},
    )


class PaddleOCRProvider(OCRProvider):
    """Read one image with PaddleOCR, lazily loading the engine if needed."""

    def __init__(self, engine: Any = None, lang: str = "ch") -> None:
        self._engine = engine
        self.lang = lang

    @property
    def engine(self) -> Any:
        if self._engine is None:
            try:
                module = importlib.import_module("paddleocr")
                factory = getattr(module, "PaddleOCR")
                self._engine = factory(lang=self.lang)
            except Exception as exc:  # ImportError, init failure, no PaddleOCR
                raise PaddleUnavailableError(
                    f"PaddleOCR unavailable: {type(exc).__name__}"
                ) from exc
        return self._engine

    def read(self, image_path: str | Path) -> OcrResult:
        target = str(image_path)
        try:
            engine = self.engine
        except PaddleUnavailableError:
            raise
        except Exception as exc:
            raise PaddleUnavailableError(
                f"PaddleOCR unavailable: {type(exc).__name__}"
            ) from exc
        try:
            predict = getattr(engine, "predict", None)
            ocr = getattr(engine, "ocr", None)
            if callable(predict):
                output = predict(target)
            elif callable(ocr):
                output = ocr(target)
            else:
                raise OcrError("paddle engine has neither predict() nor ocr()")
            rows = extract_lines(output)
            result = _build_result(rows)
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(f"paddle OCR failed: {type(exc).__name__}") from exc
        return result
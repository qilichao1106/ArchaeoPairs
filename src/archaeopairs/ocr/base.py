"""OCR provider interface and hybrid merge (T-004).

Providers (VLM now, PaddleOCR later in T-005) implement :class:`OCRProvider`
and return one :class:`OcrResult` per image.  :func:`merge_ocr_results` combines
two providers without guessing: duplicates collapse, and genuinely different
readings are kept and reported in ``raw["conflicts"]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock

__all__ = ["OCRProvider", "merge_ocr_results"]


@runtime_checkable
class OCRProvider(Protocol):
    """Anything that can read one figure image into an :class:`OcrResult`."""

    def read(self, image_path: str | Path) -> OcrResult: ...


_Item = TypeVar("_Item", SeqLabel, ScaleBar, TextBlock)
_Key = tuple[str, tuple[int, int, int, int]]


def _merge_list(
    primary: list[_Item], secondary: list[_Item]
) -> tuple[list[_Item], dict[str, list[_Key]]]:
    """Dedupe on (stripped text, bbox); primary order wins."""
    merged: list[_Item] = []
    seen: set[_Key] = set()
    by_text: dict[str, list[_Key]] = {}
    for item in [*primary, *secondary]:
        key: _Key = (item.text.strip(), tuple(item.bbox))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        by_text.setdefault(key[0], []).append(key)
    return merged, by_text


def merge_ocr_results(primary: OcrResult, secondary: OcrResult) -> OcrResult:
    """Merge two provider results into one ``source="hybrid"`` result.

    Elements are deduplicated on (stripped text, bbox).  The same text found at
    a different bbox is kept as two entries and recorded in
    ``raw["conflicts"]``.  ``primary`` ordering wins; ``raw`` keeps both
    provider payloads, the provider hit counts per text, and the conflicts.
    """
    seqs, seq_hits = _merge_list(primary.seqs, secondary.seqs)
    scales, scale_hits = _merge_list(primary.scales, secondary.scales)
    texts, text_hits = _merge_list(primary.texts, secondary.texts)

    hits_by_text: dict[str, dict[str, int]] = {}
    for kind, hits in (("seqs", seq_hits), ("scales", scale_hits), ("texts", text_hits)):
        for text, keys in hits.items():
            slot = hits_by_text.setdefault(text, {"seqs": 0, "scales": 0, "texts": 0})
            slot[kind] += len(keys)

    boxes_by_text: dict[str, list[list[int]]] = {}
    for item in [*seqs, *scales, *texts]:
        boxes = boxes_by_text.setdefault(item.text.strip(), [])
        if list(item.bbox) not in boxes:
            boxes.append(list(item.bbox))

    conflicts = [
        {
            "text": text,
            "reason": "same_text_different_bbox",
            "bboxes": boxes,
            "primary_source": primary.source,
            "secondary_source": secondary.source,
        }
        for text, boxes in boxes_by_text.items()
        if len(boxes) > 1
    ]
    return OcrResult(
        seqs=seqs,
        scales=scales,
        texts=texts,
        source="hybrid",
        raw={
            "primary": primary.model_dump(),
            "secondary": secondary.model_dump(),
            "hits_by_text": hits_by_text,
            "conflicts": conflicts,
        },
    )

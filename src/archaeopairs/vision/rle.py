"""COCO-style column-major run-length encoding for boolean masks (T-006).

Encoding is ``"{h}x{w}:{counts}"`` where ``counts`` is a comma-separated
list of run lengths.  Runs alternate starting with the background (False) and
traverse pixels column-by-column, top-to-bottom (the COCO convention), so a
mask round-trips exactly.  No ``pycocotools`` dependency is used.
"""

from __future__ import annotations

import re

import numpy as np

_RLE_RE = re.compile(r"^([1-9]\d*)x([1-9]\d*):(.*)$")


def rle_encode(mask: np.ndarray) -> str:
    """Encode a 2-D boolean mask as a COCO-style column-major RLE string."""
    array = np.asarray(mask)
    if array.ndim != 2:
        raise ValueError(f"mask must be 2-D, got shape {array.shape}")
    if array.dtype != np.bool_:
        if array.size and not np.all((array == 0) | (array == 1)):
            raise ValueError("mask must be boolean (or only 0/1)")
        array = array.astype(np.bool_)
    height, width = (int(n) for n in array.shape)
    flat = array.flatten(order="F")
    counts: list[int] = []
    previous = False
    run = 0
    for value in flat.tolist():
        if value == previous:
            run += 1
        else:
            counts.append(run)
            run = 1
            previous = value
    counts.append(run)
    return f"{height}x{width}:" + ",".join(str(n) for n in counts)


def rle_decode(rle: str) -> np.ndarray:
    """Decode an RLE string; a run total that differs from ``h*w`` raises."""
    if not isinstance(rle, str):
        raise ValueError("rle must be a string")
    match = _RLE_RE.match(rle.strip())
    if match is None:
        raise ValueError(f"malformed RLE header: {rle.split(':', 1)[0]!r}")
    height, width = int(match.group(1)), int(match.group(2))
    body = match.group(3).strip()
    total = height * width
    if body == "":
        raise ValueError("empty RLE counts")
    try:
        counts = [int(part) for part in body.split(",")]
    except ValueError as exc:
        raise ValueError(f"non-integer RLE counts: {body!r}") from exc
    if any(n < 0 for n in counts):
        raise ValueError("RLE counts must be non-negative")
    if sum(counts) != total:
        raise ValueError(
            f"RLE run total {sum(counts)} != {height}x{width} ({total})"
        )
    values: list[bool] = []
    current = False
    for run in counts:
        values.extend([current] * run)
        current = not current
    return np.asarray(values, dtype=np.bool_).reshape((height, width), order="F")

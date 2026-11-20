"""Concrete :class:`~archaeopairs.pipeline.Writer` that persists to disk.

Layout under ``out_dir``::

    pairs/<name>.png    one composed PNG per artifact image
    pairs.jsonl         one PairRecord per line (UTF-8)
    ledger.jsonl        one ledger row per line (UTF-8)

Everything goes through byte-level file I/O (``cv2.imencode`` + ``write_bytes``,
``Path.write_text``) so Windows paths containing Chinese characters work;
``cv2.imwrite`` / ``np.fromfile``-style helpers are avoided for exactly that
reason.  ``pairs.jsonl`` and ``ledger.jsonl`` are rewritten on every call, so a
re-run never mixes rows from two books.  Nothing is dropped silently: an empty
list still produces an empty (truncated) file, and any I/O problem surfaces as
``OSError``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

__all__ = ["FileWriter"]


def _to_jsonable(value: Any) -> Any:
    """Convert pydantic models / ndarray scalars into plain JSON values."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _write_jsonl(path: Path, rows: list[Any]) -> None:
    lines = [
        json.dumps(_to_jsonable(row), ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ]
    payload = "\n".join(lines) + ("\n" if lines else "")
    try:
        path.write_text(payload, encoding="utf-8", newline="\n")
    except OSError:
        raise


class FileWriter:
    """Persist images and JSONL sinks under one book output directory."""

    def __init__(self, out_dir: str | Path) -> None:
        self.out_dir = Path(out_dir)
        try:
            (self.out_dir / "pairs").mkdir(parents=True, exist_ok=True)
        except OSError:
            raise

    # -- images ------------------------------------------------------------

    def write_image(self, name: str, image: np.ndarray) -> str:
        """Encode ``image`` (BGR ndarray) as PNG; return its path relative to ``out_dir``.

        ``name`` is a bare file name such as ``图一_1_M4-1.png``; any directory
        part is discarded so a crafted name can never escape ``out_dir/pairs``.
        """
        if not isinstance(image, np.ndarray):
            raise OSError(f"image is not a numpy array: {type(image).__name__}")
        array = image if image.dtype == np.uint8 else image.astype(np.uint8)
        ok, buffer = cv2.imencode(".png", array)
        if not ok:
            raise OSError(f"PNG encoding failed for {name}")
        relative = Path("pairs") / Path(str(name)).name
        target = self.out_dir / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(buffer.tobytes())
        except OSError:
            raise
        return relative.as_posix()

    # -- JSONL sinks -------------------------------------------------------

    def write_pairs(self, records: list[dict]) -> None:
        """Overwrite ``out_dir/pairs.jsonl`` with one Pair per line."""
        _write_jsonl(self.out_dir / "pairs.jsonl", list(records))

    def write_ledger(self, rows: list[dict]) -> None:
        """Overwrite ``out_dir/ledger.jsonl`` with one ledger row per line."""
        _write_jsonl(self.out_dir / "ledger.jsonl", list(rows))
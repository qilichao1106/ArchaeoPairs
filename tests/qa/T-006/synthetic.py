"""Small synthetic-image helpers shared by the T-006 acceptance tests.

The helpers deliberately produce only 0/255 line drawings on white paper so
OTSU thresholding is unambiguous, and every image is written below pytest's
``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

WHITE = 255
INK = 0


def canvas(height: int = 160, width: int = 200) -> np.ndarray:
    """A white uint8 grayscale canvas."""
    return np.full((height, width), WHITE, dtype=np.uint8)


def rect(image: np.ndarray, box: tuple[int, int, int, int],
         value: int = INK) -> np.ndarray:
    """Fill ``box`` = ``(x0, y0, x1, y1)`` (right/bottom exclusive)."""
    x0, y0, x1, y1 = (int(n) for n in box)
    image[y0:y1, x0:x1] = value
    return image


def save_gray(path: Path, image: np.ndarray) -> Path:
    """Write a synthetic grayscale image and return its path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(image, dtype=np.uint8)).save(path)
    return path


def bbox_contains(outer: tuple[int, int, int, int],
                  inner: tuple[int, int, int, int]) -> bool:
    """True when ``inner`` lies inside ``outer`` (both half-open)."""
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return ox0 <= ix0 and oy0 <= iy0 and ix1 <= ox1 and iy1 <= oy1
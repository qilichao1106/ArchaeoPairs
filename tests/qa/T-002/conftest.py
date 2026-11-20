"""Shared fixtures for the frozen T-002 acceptance tests.

The suite is run from the project root:

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-002 -q -p no:cacheprovider

Images are synthetic and deterministic so the pixel-family assertions do not
depend on any book media.  All images are 80x60, i.e. below the classifier's
96 px downscaling threshold, so the line sample stays pure black/white and is
never anti-aliased into a gray photo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def make_image(tmp_path):
    """Return a factory producing a deterministic line/gray/color PNG."""

    def _make(kind: str) -> Path:
        path = tmp_path / f"{kind}.png"
        if kind == "line":
            img = Image.new("RGB", (80, 60), "white")
            draw = ImageDraw.Draw(img)
            draw.rectangle((15, 10, 65, 45), outline="black", width=1)
            draw.ellipse((30, 20, 50, 40), outline="black", width=1)
            draw.line((5, 52, 75, 52), fill="black", width=1)
            img.save(path)
        elif kind == "gray":
            rng = np.random.default_rng(20261120)
            arr = rng.integers(0, 256, size=(60, 80), dtype=np.uint8)
            Image.fromarray(arr).convert("RGB").save(path)
        elif kind == "color":
            rng = np.random.default_rng(7)
            arr = rng.integers(0, 256, size=(60, 80, 3), dtype=np.uint8)
            Image.fromarray(arr).save(path)
        else:  # pragma: no cover - guards a typo in the tests themselves
            raise ValueError(f"unknown image kind: {kind}")
        assert path.is_file(), path
        return path

    return _make
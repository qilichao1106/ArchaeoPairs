"""Frozen T-006 acceptance tests for ``load_image``.

``load_image`` must use a filesystem-safe read (``np.fromfile`` plus
``cv2.imdecode``) so Windows paths containing Chinese characters work, and it
must normalise failures to ``OSError``.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from archaeopairs.vision import load_image


def test_load_image_reads_a_chinese_path_as_bgr(tmp_path) -> None:
    rgb = np.zeros((12, 16, 3), dtype=np.uint8)
    rgb[..., 0] = 255  # red in RGB
    path = tmp_path / "中文 目录" / "图版_一.png"
    path.parent.mkdir(parents=True)
    Image.fromarray(rgb).save(path)

    loaded = load_image(str(path))

    assert loaded.shape == (12, 16, 3)
    # cv2 decodes colour images as BGR: red RGB becomes (0, 0, 255).
    assert tuple(int(value) for value in loaded[0, 0]) == (0, 0, 255)
    assert tuple(int(value) for value in loaded[11, 15]) == (0, 0, 255)
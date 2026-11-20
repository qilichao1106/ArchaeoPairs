"""Frozen T-006 negative controls.

Each test feeds input that carries no usable image evidence, or a mask pair
that cannot be compared, and asserts the documented failure/no-result outcome.
These are the negative counterparts of the positive segmentation tests: a
"segment everything" or "accept any shape" regression must turn them red.
"""

from __future__ import annotations

import numpy as np
import pytest

from archaeopairs.vision import load_image, segment_views
from synthetic import canvas, save_gray


def test_negative_missing_image_raises_oserror(tmp_path) -> None:
    with pytest.raises(OSError):
        load_image(tmp_path / "不存在.png")


def test_negative_empty_file_raises_oserror(tmp_path) -> None:
    path = tmp_path / "空图.png"
    path.write_bytes(b"")

    with pytest.raises(OSError):
        load_image(path)


def test_negative_non_image_file_raises_oserror(tmp_path) -> None:
    path = tmp_path / "不是图片.png"
    path.write_bytes(b"this is not an image")

    with pytest.raises(OSError):
        load_image(path)


def test_negative_directory_path_raises_oserror(tmp_path) -> None:
    path = tmp_path / "目录.png"
    path.mkdir()

    with pytest.raises(OSError):
        load_image(path)


def test_negative_blank_white_image_yields_no_views(tmp_path) -> None:
    path = save_gray(tmp_path / "white.png", canvas(90, 120))

    assert segment_views(path) == []


def test_negative_3x3_speck_does_not_become_a_view(tmp_path) -> None:
    image = canvas(80, 80)
    image[20:23, 20:23] = 0  # 9 pixels, below min_area 15
    path = save_gray(tmp_path / "speck.png", image)

    views = segment_views(path)

    assert views == []


def test_negative_mask_iou_shape_mismatch_raises() -> None:
    from archaeopairs.vision import mask_iou

    with pytest.raises(ValueError):
        mask_iou(np.zeros((3, 3), dtype=bool), np.zeros((3, 4), dtype=bool))
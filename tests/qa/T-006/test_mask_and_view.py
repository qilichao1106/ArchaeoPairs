"""Frozen T-006 acceptance tests for masks, IoU, ``View`` and the exports.

The mask must be filled from the contour itself (never the bbox rectangle),
the bbox must contain every mask pixel, and ``View.area`` must equal the
number of mask pixels.
"""

from __future__ import annotations

import numpy as np
import pytest

import archaeopairs.vision as vision
from archaeopairs.models import View
from archaeopairs.vision.rle import rle_decode, rle_encode
from archaeopairs.vision.seg import (
    extract_contours,
    filled_mask,
    load_image,
    mask_iou,
    segment_views,
)
from t006_synthetic import canvas, rect, save_gray


def test_view_bbox_contains_the_mask_and_area_matches_mask_sum(tmp_path) -> None:
    image = canvas(80, 100)
    block = (30, 20, 50, 40)
    rect(image, block)
    path = save_gray(tmp_path / "block.png", image)

    views = segment_views(path)
    assert len(views) == 1
    view = views[0]
    mask = rle_decode(view.mask_rle)

    assert mask.shape == image.shape
    assert mask.dtype == np.bool_
    rows, cols = np.nonzero(mask)
    assert rows.size > 0

    x0, y0, x1, y1 = view.bbox
    assert 0 <= x0 < x1 <= image.shape[1]
    assert 0 <= y0 < y1 <= image.shape[0]
    assert x0 <= int(cols.min()) and int(cols.max()) < x1
    assert y0 <= int(rows.min()) and int(rows.max()) < y1
    assert int(mask[y0:y1, x0:x1].sum()) == int(mask.sum())
    assert view.area == int(mask.sum()) == int(rows.size)
    assert view.view_id == 0
    assert view.incomplete is False


def test_filled_mask_fills_the_contour_not_its_bbox() -> None:
    contour = np.array([[[10, 10]], [[50, 10]], [[10, 50]]], dtype=np.int32)
    mask = filled_mask(contour, (60, 60))

    assert mask.shape == (60, 60)
    assert mask.dtype == np.bool_
    assert bool(mask[15, 15]) is True
    # (45, 45) is inside the contour bbox but outside the triangle.
    assert bool(mask[45, 45]) is False
    assert bool(mask[0, 0]) is False

    same = filled_mask(contour.reshape(-1, 2), (60, 60))
    assert np.array_equal(same, mask)


def test_mask_iou_identical_disjoint_and_partial() -> None:
    a = np.zeros((4, 4), dtype=bool)
    a[1:3, 1:3] = True
    assert mask_iou(a, a) == 1.0

    b = np.zeros((4, 4), dtype=bool)
    b[3, 3] = True
    assert mask_iou(a, b) == 0.0

    left = np.array([[True, True], [False, False]])
    right = np.array([[False, True], [False, True]])
    assert mask_iou(left, right) == pytest.approx(1.0 / 3.0)


def test_mask_iou_rejects_different_shapes() -> None:
    with pytest.raises(ValueError):
        mask_iou(np.zeros((2, 2), dtype=bool), np.zeros((2, 3), dtype=bool))


def test_view_model_has_the_frozen_fields() -> None:
    view = View(
        view_id=2,
        bbox=(1, 2, 30, 40),
        area=12,
        mask_rle="4x4:16",
    )

    assert set(View.model_fields) == {
        "view_id",
        "bbox",
        "area",
        "mask_rle",
        "incomplete",
    }
    assert isinstance(view.bbox, tuple)
    assert view.view_id == 2
    assert tuple(view.bbox) == (1, 2, 30, 40)
    assert view.area == 12
    assert view.mask_rle == "4x4:16"
    assert view.incomplete is False


def test_vision_package_exports_the_public_surface() -> None:
    expected = {
        "View",
        "extract_contours",
        "filled_mask",
        "load_image",
        "mask_iou",
        "rle_decode",
        "rle_encode",
        "segment_views",
    }

    assert set(vision.__all__) == expected
    assert len(vision.__all__) == len(expected)
    assert vision.View is View
    assert vision.extract_contours is extract_contours
    assert vision.filled_mask is filled_mask
    assert vision.load_image is load_image
    assert vision.mask_iou is mask_iou
    assert vision.rle_decode is rle_decode
    assert vision.rle_encode is rle_encode
    assert vision.segment_views is segment_views
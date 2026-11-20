"""Frozen T-006 acceptance tests for contour extraction and ``segment_views``.

All figures are synthetic line drawings written under ``tmp_path``.  The
reading order is top-to-bottom, then left-to-right; noise below ``min_area``
is dropped; hole contours are filled away and only the outer contour is kept.
"""

from __future__ import annotations

import numpy as np

from archaeopairs.vision import extract_contours, rle_decode, segment_views
from synthetic import bbox_contains, canvas, rect, save_gray


def _mask(view):
    return rle_decode(view.mask_rle)


def test_two_separated_blocks_are_numbered_in_reading_order(tmp_path) -> None:
    image = canvas(160, 200)
    top_right = (140, 20, 160, 40)
    bottom_left = (20, 100, 40, 120)
    rect(image, top_right)
    rect(image, bottom_left)
    path = save_gray(tmp_path / "two_blocks.png", image)

    views = segment_views(path)

    assert len(views) == 2
    assert [view.view_id for view in views] == [0, 1]
    assert bbox_contains(views[0].bbox, top_right)
    assert bbox_contains(views[1].bbox, bottom_left)

    first, second = _mask(views[0]), _mask(views[1])
    assert bool(first[25, 145]) is True       # inside the top-right block
    assert bool(second[105, 25]) is True      # inside the bottom-left block
    assert bool(first[105, 25]) is False
    assert not np.any(first & second)


def test_four_blocks_are_ordered_top_to_bottom_then_left_to_right(
    tmp_path,
) -> None:
    image = canvas(160, 200)
    top_left = (20, 20, 40, 40)
    top_right = (140, 20, 160, 40)
    bottom_left = (20, 100, 40, 120)
    bottom_right = (140, 100, 160, 120)
    for box in (top_left, top_right, bottom_left, bottom_right):
        rect(image, box)
    path = save_gray(tmp_path / "four_blocks.png", image)

    views = segment_views(path)

    assert len(views) == 4
    assert [view.view_id for view in views] == [0, 1, 2, 3]
    for view, box in zip(
        views, (top_left, top_right, bottom_left, bottom_right), strict=True
    ):
        assert bbox_contains(view.bbox, box)

    reading_keys = [(view.bbox[1], view.bbox[0]) for view in views]
    assert reading_keys == sorted(reading_keys)

    masks = [_mask(view) for view in views]
    for index, first in enumerate(masks):
        for second in masks[index + 1:]:
            assert not np.any(first & second)


def test_3x3_noise_is_dropped_and_4x4_ink_is_kept(tmp_path) -> None:
    image = canvas(100, 140)
    noise = (20, 20, 23, 23)       # 9 pixels < min_area 15
    block = (80, 30, 84, 34)       # 16 pixels >= min_area 15
    rect(image, noise)
    rect(image, block)
    path = save_gray(tmp_path / "noise_and_block.png", image)

    views = segment_views(path)

    assert len(views) == 1
    view = views[0]
    assert bbox_contains(view.bbox, block)
    mask = _mask(view)
    assert bool(mask[32, 82]) is True              # inside the 4x4 block
    assert not mask[noise[1]:noise[3], noise[0]:noise[2]].any()
    assert view.area == int(mask.sum())

    kept, _removed, _binary = extract_contours(image)
    assert len(kept) == 1
    assert bbox_contains(kept[0]["bbox"], block)


def test_hole_is_filled_and_only_the_outer_contour_is_kept(tmp_path) -> None:
    image = canvas(140, 140)
    outer = (30, 30, 90, 90)
    hole = (40, 40, 80, 80)
    rect(image, outer)
    rect(image, hole, 255)
    path = save_gray(tmp_path / "ring.png", image)

    kept, removed, _binary = extract_contours(image)
    assert len(kept) == 1
    assert bbox_contains(kept[0]["bbox"], outer)
    assert any(item["hole"] is True for item in removed)

    views = segment_views(path)
    assert len(views) == 1
    view = views[0]
    assert bbox_contains(view.bbox, outer)

    mask = _mask(view)
    assert bool(mask[35, 35]) is True    # on the black ring
    assert bool(mask[60, 60]) is True    # the white hole is filled
    assert view.area == int(mask.sum())


def test_contour_inside_a_larger_contour_is_removed(tmp_path) -> None:
    # A ring plus a separate square inside its white hole.  RETR_CCOMP puts the
    # inner object back at the top level, so it must be removed by the
    # "all four corners inside a larger contour" rule, not by parent lookup.
    image = canvas(180, 180)
    outer = (30, 30, 100, 100)
    hole = (40, 40, 90, 90)
    contained = (55, 55, 75, 75)
    rect(image, outer)
    rect(image, hole, 255)
    rect(image, contained)
    path = save_gray(tmp_path / "contained.png", image)

    kept, _removed, _binary = extract_contours(image)

    # The inner object must not survive as a kept contour; the only kept
    # contour is the outer ring.
    assert len(kept) == 1
    assert bbox_contains(kept[0]["bbox"], outer)

    views = segment_views(path)
    assert len(views) == 1
    assert bbox_contains(views[0].bbox, outer)


def test_pure_white_image_has_no_views(tmp_path) -> None:
    image = canvas(120, 160)
    path = save_gray(tmp_path / "blank.png", image)

    assert segment_views(path) == []

    kept, removed, binary = extract_contours(image)
    assert kept == []
    assert removed == []
    assert binary.shape == image.shape
    assert set(np.unique(binary)) <= {0, 255}
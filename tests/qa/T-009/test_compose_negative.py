"""T-009 negative controls: broken masks/views must raise ComposeError.

These inject real faults (an all-false mask, an absent view, a wrong-size
mask, a malformed RLE, an empty scale bbox, a bad dtype) rather than using a
fake assertion; every one must fail composition instead of silently emitting
a wrong PNG.
"""

from __future__ import annotations

import numpy as np
import pytest

from archaeopairs.compose import ComposeError, compose_unit
from archaeopairs.models import ScaleBar, View
from archaeopairs.vision.rle import rle_encode

from t009_synthetic import (
    BLOCK_A,
    H,
    W,
    binding,
    make_image,
    unit_for,
    view_for,
)


def test_negative_empty_view_mask_raises() -> None:
    image = make_image()
    empty = View(
        view_id=5,
        bbox=(0, 0, 1, 1),
        area=0,
        mask_rle=rle_encode(np.zeros((H, W), dtype=np.bool_)),
    )

    with pytest.raises(ComposeError, match="empty"):
        compose_unit(image, unit_for("X", view_ids=(5,)), {5: empty}, {})


def test_negative_blank_mask_rle_raises() -> None:
    image = make_image()
    blank = View(view_id=0, bbox=BLOCK_A, area=0, mask_rle="")

    with pytest.raises(ComposeError, match="empty mask_rle"):
        compose_unit(image, unit_for("X", view_ids=(0,)), {0: blank}, {})


def test_negative_missing_view_raises() -> None:
    image = make_image()
    unit = unit_for("X", view_ids=(404,))

    with pytest.raises(ComposeError, match="not found"):
        compose_unit(image, unit, {0: view_for(0, BLOCK_A)}, {})


def test_negative_unit_without_view_ids_raises() -> None:
    image = make_image()
    unit = unit_for("X", view_ids=())

    with pytest.raises(ComposeError, match="no view_ids"):
        compose_unit(image, unit, {}, {})


def test_negative_mask_shape_mismatch_raises() -> None:
    image = make_image()
    wrong_shape = np.ones((60, 100), dtype=np.bool_)
    wrong = View(
        view_id=0,
        bbox=(0, 0, 100, 60),
        area=int(wrong_shape.sum()),
        mask_rle=rle_encode(wrong_shape),
    )

    with pytest.raises(ComposeError, match="does not match"):
        compose_unit(image, unit_for("X", view_ids=(0,)), {0: wrong}, {})


def test_negative_malformed_rle_raises() -> None:
    image = make_image()
    malformed = View(
        view_id=0, bbox=BLOCK_A, area=1, mask_rle="not-an-rle"
    )

    with pytest.raises(ComposeError, match="cannot decode"):
        compose_unit(image, unit_for("X", view_ids=(0,)), {0: malformed}, {})


@pytest.mark.parametrize(
    "scale_bbox",
    [
        (10, 10, 10, 10),  # zero width
        (20, 108, 10, 113),  # inverted width
        (500, 500, 600, 600),  # entirely outside the 200x120 image
    ],
)
def test_negative_empty_scale_bbox_raises(scale_bbox) -> None:
    image = make_image()
    unit = unit_for("X", view_ids=(0,), bindings=(binding(0),))
    scale = ScaleBar(text="?", bbox=scale_bbox)

    with pytest.raises(ComposeError, match="empty"):
        compose_unit(image, unit, {0: view_for(0, BLOCK_A)}, {0: scale})


def test_negative_non_8bit_image_raises() -> None:
    image = np.full((H, W, 3), 255.0, dtype=np.float32)
    unit = unit_for("X", whole_image=True)

    with pytest.raises(ComposeError, match="8-bit"):
        compose_unit(image, unit, {}, {})
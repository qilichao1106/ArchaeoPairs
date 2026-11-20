"""Frozen T-006 acceptance tests for the COCO-style RLE codec.

The wire format is ``"{h}x{w}:{counts}"`` with column-major runs that start
with the background run.  Bad input must raise ``ValueError``; a run total
that differs from ``h*w`` is bad input.
"""

from __future__ import annotations

import numpy as np
import pytest

from archaeopairs.vision.rle import rle_decode, rle_encode


def _round_trip_masks() -> list[np.ndarray]:
    zeros = np.zeros((3, 4), dtype=bool)
    ones = np.ones((3, 4), dtype=bool)
    checker = (np.indices((5, 7)).sum(axis=0) % 2) == 0
    single = np.zeros((4, 5), dtype=bool)
    single[0, 0] = True
    diagonal = np.eye(6, dtype=bool)
    random = np.random.default_rng(20261120).random((7, 9)) > 0.55
    return [zeros, ones, checker, single, diagonal, random]


@pytest.mark.parametrize(
    "mask",
    _round_trip_masks(),
    ids=["empty", "full", "checker", "single-pixel", "diagonal", "random"],
)
def test_rle_round_trip_is_exact(mask: np.ndarray) -> None:
    encoded = rle_encode(mask)
    decoded = rle_decode(encoded)

    assert decoded.shape == mask.shape
    assert decoded.dtype == np.bool_
    assert np.array_equal(decoded, mask)


def test_rle_is_column_major_and_starts_with_background_run() -> None:
    # 2x2, only the top-right pixel is set.  Column-major flattening yields
    # (0,0)=F, (1,0)=F, (0,1)=T, (1,1)=F  ->  2 background, 1 ink, 1 background.
    mask = np.zeros((2, 2), dtype=bool)
    mask[0, 1] = True

    assert rle_encode(mask) == "2x2:2,1,1"
    decoded = rle_decode("2x2:2,1,1")
    assert bool(decoded[0, 1]) is True
    assert bool(decoded[0, 0]) is False

    assert rle_encode(np.ones((2, 2), dtype=bool)) == "2x2:0,4"
    assert rle_encode(np.zeros((2, 2), dtype=bool)) == "2x2:4"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "nonsense",
        "2x2",
        "2x2:",
        "0x2:0,0",
        "x2:4",
        "2x2:2,1",       # total 3 != 4
        "2x2:5",         # total 5 != 4
        "2x2:a,b",       # non-integer run
        "2x2:1,-1,4",    # negative run
    ],
)
def test_bad_rle_string_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        rle_decode(bad)


@pytest.mark.parametrize("bad", [None, 12, b"2x2:4"])
def test_bad_rle_type_raises_value_error(bad: object) -> None:
    with pytest.raises(ValueError):
        rle_decode(bad)  # type: ignore[arg-type]
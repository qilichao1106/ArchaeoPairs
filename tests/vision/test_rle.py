"""vision/rle 编解码契约：round-trip 逐像素精确（迁移风险 3 的防线）。"""
from __future__ import annotations

import numpy as np

from archaeopairs.vision import rle_decode, rle_encode


def test_roundtrip_random_masks():
    rng = np.random.default_rng(42)
    for shape in [(20, 30), (100, 7), (1, 1), (64, 64)]:
        m = rng.random(shape) > 0.5
        assert np.array_equal(rle_decode(rle_encode(m)), m), shape


def test_roundtrip_degenerate_masks():
    h, w = 25, 40
    empty = np.zeros((h, w), bool)
    full = np.ones((h, w), bool)
    assert np.array_equal(rle_decode(rle_encode(empty)), empty)
    assert np.array_equal(rle_decode(rle_encode(full)), full)


def test_roundtrip_single_pixel_runs():
    m = np.zeros((5, 5), bool)
    m[2, 2] = True
    m[4, 0] = True
    assert np.array_equal(rle_decode(rle_encode(m)), m)


def test_encode_format_prefix():
    rle = rle_encode(np.zeros((12, 34), bool))
    assert rle.startswith("12x34:")
    counts = [int(c) for c in rle.split(":", 1)[1].split(",")]
    assert sum(counts) == 12 * 34


def test_decode_bad_total_raises():
    import pytest

    with pytest.raises(ValueError):
        rle_decode("10x10:50")  # 行程总长 50 != 100

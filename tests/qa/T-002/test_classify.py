"""T-002 classify acceptance: line/gray/color, single/multi, keyword fallbacks."""

from __future__ import annotations

import pytest

from archaeopairs.classify.image_type import (
    classify,
    classify_image_type,
    work_line_of,
)
from archaeopairs.models import ImageType, WorkLine


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("line", ImageType.SINGLE_LINE),
        ("gray", ImageType.SINGLE_PLATE),
        ("color", ImageType.SINGLE_PLATE),
    ],
)
def test_single_artifact_family(make_image, kind, expected):
    image = make_image(kind)
    assert (
        classify_image_type("图二一二 铜舟", "1. 铜舟（M4：6）", image) == expected
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("line", ImageType.MULTI_LINE),
        ("gray", ImageType.MULTI_PLATE),
        ("color", ImageType.MULTI_PLATE),
    ],
)
def test_multi_artifact_family(make_image, kind, expected):
    image = make_image(kind)
    assert (
        classify_image_type(
            "图二一三 陶豆、陶壶",
            "1、2. 陶豆（M4：1）、陶壶（M4：2）",
            image,
        )
        == expected
    )


def test_zero_artifacts_is_discarded_regardless_of_pixels(make_image):
    for kind in ("line", "gray", "color"):
        image = make_image(kind)
        assert (
            classify_image_type("图二一二 铜舟", "0 8厘米", image)
            == ImageType.DISCARDED
        )


def test_negative_control_no_artifact_never_gets_a_line_work_line(make_image):
    """Real negative case: N=0 discards even for a perfectly good line image."""
    image = make_image("line")
    image_type = classify_image_type("图二一二 铜舟（无器物号）", None, image)
    assert image_type == ImageType.DISCARDED
    assert work_line_of(image_type) == WorkLine.ARCHIVE


@pytest.mark.parametrize("word", ["拓片", "拓本", "拓印", "线描", "摹写"])
def test_rub_word_on_gray_photo_forces_line(make_image, word):
    image = make_image("gray")
    assert (
        classify_image_type(f"图二一二 铜舟{word}", "1. 铜舟（M4：6）", image)
        == ImageType.SINGLE_LINE
    )


def test_rub_word_does_not_override_color(make_image):
    image = make_image("color")
    assert (
        classify_image_type("图二一二 铜舟拓片", "1. 铜舟（M4：6）", image)
        == ImageType.SINGLE_PLATE
    )


def test_missing_image_with_plate_keyword_falls_back_to_plate():
    assert (
        classify_image_type("图版三 铜舟（M4：6）", None, None)
        == ImageType.SINGLE_PLATE
    )


def test_unreadable_image_with_plate_keyword_falls_back_to_plate(tmp_path):
    missing = tmp_path / "does_not_exist.png"
    assert (
        classify_image_type("图版三 铜舟（M4：6）", None, missing)
        == ImageType.SINGLE_PLATE
    )


def test_missing_image_without_plate_keyword_falls_back_to_line():
    assert (
        classify_image_type("图二一二 铜舟（M4：6）", None, None)
        == ImageType.SINGLE_LINE
    )


def test_rub_word_overrides_plate_keyword_when_image_is_missing():
    assert (
        classify_image_type("图版三 铜舟拓片（M4：6）", None, None)
        == ImageType.SINGLE_LINE
    )


def test_missing_image_multi_artifact_with_plate_keyword():
    assert (
        classify_image_type("图版三 铜舟、陶豆（M4：6、M4：7）", None, None)
        == ImageType.MULTI_PLATE
    )


def test_classify_returns_image_type_and_work_line(make_image):
    assert classify("图版三 铜舟（M4：6）", None, None) == (
        ImageType.SINGLE_PLATE,
        WorkLine.SINGLE_PLATE,
    )
    line_image = make_image("line")
    assert classify("图二一二 铜舟", "1. 铜舟（M4：6）", line_image) == (
        ImageType.SINGLE_LINE,
        WorkLine.SINGLE_LINE,
    )
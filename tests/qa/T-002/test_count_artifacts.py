"""T-002 count_artifacts acceptance: note-first counting, suffixes, dedup, noise."""

from __future__ import annotations

import pytest

from archaeopairs.classify.image_type import count_artifacts


@pytest.mark.parametrize(
    ("caption", "figure_note", "expected"),
    [
        # Figure note is the primary source.
        ("图二一二 铜舟", "1. 铜舟（M4：6）", 1),
        ("图二一三 铁削", "1、2. 铁削（M43：75a、M43：75b）", 2),
        # Note wins even when the caption carries more ids.
        ("图2-1-5 铜鼎（M4:6、M4:7、M4:8）纹饰", "1. 陶豆（M4:1） 2. 陶壶（M4:2）", 2),
        # Caption is the fallback only when the note has no artifact id.
        ("图二一二 铜舟（M4：7）", "0 8厘米", 1),
        ("M4:6、M4:7", None, 2),
        # Letter suffixes are distinct artifacts (R-ID-06).
        ("M43:75a、M43:75b、M43:75c", None, 3),
        ("标本M43：75a……75b……75c", None, 3),
        ("M43:75a、M43:75a", None, 1),
        # -N sub-numbers are distinct artifacts.
        ("M39:8-1、M39:8-2", None, 2),
        # Full-width, half-width and ratio colons normalize to one id shape.
        ("2004CWWM11：5", None, 1),
        ("00FBH1:6", None, 1),
        ("M4:6、M4：6、M4∶6", None, 1),
        # Scale text and figure numbers are never artifact ids.
        ("图二一二 铜舟", "0 8厘米", 0),
        ("图2-1-16 铜舟", None, 0),
        ("图版三 铜舟", "比例尺 0 8厘米", 0),
        (None, None, 0),
        ("", "", 0),
    ],
)
def test_count_artifacts(caption, figure_note, expected):
    assert count_artifacts(caption, figure_note) == expected


def test_negative_control_scale_and_figure_number_are_not_artifacts():
    """Real negative case: non-artifact text must yield zero, not a guess."""
    assert count_artifacts("图二一二 铜舟", "0 8厘米") == 0
    assert count_artifacts("图2-1-16 铜舟", "比例尺 0 8厘米") == 0
    assert count_artifacts("图版三 陶豆", None) == 0
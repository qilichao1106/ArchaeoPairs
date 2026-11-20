"""T-003 artifact-id normalization/extraction (card §1, R-ID-01..06).

Frozen expectations:

* ``:`` / ``：`` / ``∶`` normalize to one half-width colon with the incidental
  whitespace folded away; case, ``75a`` suffix letters and ``8-1`` sub-numbers
  stay part of the id.
* extraction keeps first-appearance order and de-duplicates.
* scale text (``0 8厘米``), Chinese figure numbers and figure sub-numbers
  (``图2-1-16``) are never ids; a bare ``Bb9`` (no colon) is name evidence only.
"""

from __future__ import annotations

import pytest

from archaeopairs.text.artifact_id import extract_artifacts, normalize_artifact_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("M4:6", "M4:6"),
        ("M4：6", "M4:6"),
        ("M4∶6", "M4:6"),
        ("M4 ∶ 6", "M4:6"),
        (" 2004CWWM11 ： 5 ", "2004CWWM11:5"),
        ("M43:75a", "M43:75a"),
        ("M39:8-1", "M39:8-1"),
        ("ZhB2:7", "ZhB2:7"),
    ],
)
def test_normalize_artifact_id(raw, expected):
    assert normalize_artifact_id(raw) == expected


def test_normalize_preserves_suffix_letters_and_subnumbers():
    """R-ID-06: ``75a`` / ``8-1`` are identity, never collapsed onto a stem."""
    assert normalize_artifact_id(" M43 ∶ 75a ") == "M43:75a"
    assert normalize_artifact_id("M39：8-1") == "M39:8-1"
    assert normalize_artifact_id("M43:75a") != normalize_artifact_id("M43:75b")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("M4:6", ["M4:6"]),
        ("2004CWWM11：5", ["2004CWWM11:5"]),
        ("00FBH1:6", ["00FBH1:6"]),
        ("M43:75a", ["M43:75a"]),
        ("M39:8-1", ["M39:8-1"]),
        ("标本M4:6，铜舟", ["M4:6"]),
        ("M4:2、M4:1", ["M4:2", "M4:1"]),
    ],
)
def test_extract_artifact_id_shapes(text, expected):
    assert extract_artifacts(text) == expected


def test_extract_keeps_first_appearance_order_and_dedupes():
    assert extract_artifacts("M4:2、M4:1、M4:2") == ["M4:2", "M4:1"]
    assert extract_artifacts("M4:6，M4:1；M4:2") == ["M4:6", "M4:1", "M4:2"]


def test_suffix_letters_and_subnumbers_are_independent_artifacts():
    """``75a``/``75b``/``75c`` and ``8-1``/``8-2`` must not be merged."""
    letters = extract_artifacts("M43:75a、M43:75b、M43:75c")
    assert letters == ["M43:75a", "M43:75b", "M43:75c"]
    assert "M43:75" not in letters

    subnumbers = extract_artifacts("M39:8-1、M39:8-2")
    assert subnumbers == ["M39:8-1", "M39:8-2"]


@pytest.mark.parametrize(
    "text",
    [
        "0 8厘米",
        "比例尺 0 8厘米",
        "图二一二",
        "图2-1-16",
        "图版三 铜舟",
    ],
)
def test_non_artifact_text_never_produces_an_id(text):
    assert extract_artifacts(text) == []
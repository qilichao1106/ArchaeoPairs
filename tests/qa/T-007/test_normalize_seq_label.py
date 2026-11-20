"""T-007 normalize_seq_label: one seq label normalizes, group labels do not.

Frozen expectations (card §2):

* ``"1."`` / ``"1、"`` / ``"1"`` / ``"①"`` -> ``"1"``;
* a group/range label such as ``"2、3"`` is not a single seq -> ``None`` and is
  left to the group-label parser.
"""

from __future__ import annotations

import pytest

from archaeopairs.mapping import normalize_seq_label


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.", "1"),
        ("1、", "1"),
        ("1", "1"),
        ("①", "1"),
        (" 1. ", "1"),
        ("3．", "3"),
        ("⑩", "10"),
    ],
)
def test_single_seq_labels_normalize_to_bare_id(text: str, expected: str) -> None:
    assert normalize_seq_label(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "2、3",
        "2、3.",
        "1、2",
        "1、2.",
        "1～4",
        "1~4",
        "1-4",
        "1,2",
        "1，2",
        "1.2",
    ],
)
def test_negative_group_or_range_labels_return_none(text: str) -> None:
    assert normalize_seq_label(text) is None


@pytest.mark.parametrize("text", ["", "   ", "图", "序号", None])
def test_negative_blank_or_non_seq_text_returns_none(text) -> None:
    assert normalize_seq_label(text) is None
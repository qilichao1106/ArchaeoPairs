"""AC-07: figure-number extraction, colon folding, seq/01 and dedup naming."""

from __future__ import annotations

import pytest

from archaeopairs.naming import (
    build_image_name,
    dedup_name,
    extract_fig_number,
    path_artifact,
)


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("图2-1-16 M4出土铜舟、盘、圆纹饰拓片", "图2-1-16"),
        ("图七", "图七"),
        ("图二六 M4出土器物", "图二六"),
        ("图版204", "图版204"),
        ("图版 204 单器物版图", "图版204"),
        ("拓片三七", "拓片三七"),
        ("拓本三八 M4出土", "拓本三八"),
        ("图七a 盖顶面纹饰", "图七a"),
        ("图2-1-16b 局部", "图2-1-16b"),
        ("图一三 M9出土器物", "图一三"),
        ("图 2-1-5 M4出土铜鼎", "图2-1-5"),
        ("图二四七 M43出土器物", "图二四七"),
    ],
)
def test_extract_fig_number_keeps_number_prefix_and_suffix(
    caption: str, expected: str
) -> None:
    assert extract_fig_number(caption) == expected


@pytest.mark.parametrize(
    "caption",
    [None, "", "   ", "M4出土铜鼎", "图示", "图", "图版", "拓片"],
)
def test_extract_fig_number_falls_back_when_no_number_is_present(caption) -> None:
    assert extract_fig_number(caption) == "图"
    assert extract_fig_number(caption, fallback="图X") == "图X"


@pytest.mark.parametrize(
    ("artifact_id", "expected"),
    [
        ("M43:75a", "M43-75a"),
        ("M39：8-1", "M39-8-1"),
        ("M4∶2", "M4-2"),
        ("M4: 2", "M4-2"),
        (" M4 : 75a ", "M4-75a"),
        ("A：B∶C:D", "A-B-C-D"),
        ("M43-75a", "M43-75a"),
    ],
)
def test_path_artifact_folds_all_colons_and_drops_whitespace(
    artifact_id: str, expected: str
) -> None:
    assert path_artifact(artifact_id) == expected


@pytest.mark.parametrize(
    ("fig_number", "seq", "artifact_id", "expected"),
    [
        ("图2-1-16", "1", "M4:2", "图2-1-16_1_M4-2.png"),
        ("图2-1-5", None, "M4:6", "图2-1-5_01_M4-6.png"),
        ("图一三", "1,2", "M9:6", "图一三_1,2_M9-6.png"),
        ("图二四七", "5", "M43:75a", "图二四七_5_M43-75a.png"),
        ("图版204", None, "M321:2-3", "图版204_01_M321-2-3.png"),
        ("图七a", "5", "M43:75b", "图七a_5_M43-75b.png"),
        ("图2-1-16b M4出土", None, "M4:2", "图2-1-16b_01_M4-2.png"),
        ("图七", "", "M4:2", "图七_01_M4-2.png"),
        ("图七", "   ", "M4:2", "图七_01_M4-2.png"),
        ("图七", "01", "M4:2", "图七_01_M4-2.png"),
        ("图七", " 2,3 ", "M4:2", "图七_2,3_M4-2.png"),
        ("图版204", "5", " M321 : 2-3 ", "图版204_5_M321-2-3.png"),
    ],
)
def test_build_image_name_uses_figure_seq_and_folded_artifact(
    fig_number, seq, artifact_id: str, expected: str
) -> None:
    assert build_image_name(fig_number, seq, artifact_id) == expected


def test_dedup_appends_suffix_before_the_extension() -> None:
    registry: dict[str, int] = {}
    names = [dedup_name("图七_01_M4-6.png", registry) for _ in range(3)]

    assert names == [
        "图七_01_M4-6.png",
        "图七_01_M4-6_1.png",
        "图七_01_M4-6_2.png",
    ]
    assert registry["图七_01_M4-6_1.png"] >= 1
    assert dedup_name("图七_01_M4-7.png", registry) == "图七_01_M4-7.png"


def test_dedup_registry_is_shared_per_book_and_reusable_for_the_next_book() -> None:
    first_book: dict[str, int] = {}
    second_book: dict[str, int] = {}

    assert dedup_name("图七_01_M4-6.png", first_book) == "图七_01_M4-6.png"
    assert dedup_name("图七_01_M4-6.png", first_book) == "图七_01_M4-6_1.png"
    assert dedup_name("图七_01_M4-6.png", second_book) == "图七_01_M4-6.png"


def test_dedup_keeps_interleaved_names_independent() -> None:
    registry: dict[str, int] = {}
    produced = [
        dedup_name(name, registry)
        for name in ["a.png", "b.png", "a.png", "a.png", "b.png"]
    ]

    assert produced == ["a.png", "b.png", "a_1.png", "a_2.png", "b_1.png"]


def test_dedup_skips_a_suffix_already_taken_by_another_name() -> None:
    registry: dict[str, int] = {}

    assert dedup_name("a_1.png", registry) == "a_1.png"
    assert dedup_name("a.png", registry) == "a.png"
    # a_1.png is already registered, so the collision advances to a_2.png.
    assert dedup_name("a.png", registry) == "a_2.png"


def test_dedup_works_without_an_extension() -> None:
    registry: dict[str, int] = {}

    assert dedup_name("abc", registry) == "abc"
    assert dedup_name("abc", registry) == "abc_1"
    assert dedup_name("abc", registry) == "abc_2"
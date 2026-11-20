"""T-003 figure-note parsing + caption fallback (card §2, R-SEQ-01, R-MAP-01).

Every clause is a :class:`NoteItem` with the original seq fragment, the expanded
``seq_list``, the name and the note-local artifact ids.  The card's syntax list
is covered one test per shape: dot clauses, grouped/range seqs, circled and
letter seqs, the TeX range form, glued ids, scale noise and id-less clauses.
"""

from __future__ import annotations

import pytest

from archaeopairs.text.note import extract_caption_artifacts, parse_note


def test_dot_clause_without_space():
    items = parse_note("1.骨笄")
    assert len(items) == 1
    item = items[0]
    assert item.seq == "1"
    assert item.seq_list == [1]
    assert item.name == "骨笄"
    assert item.artifact_ids == []


def test_two_dot_clauses_separated_by_space():
    items = parse_note("1. 陶豆 2. 陶壶")
    assert [(i.seq, i.seq_list, i.name) for i in items] == [
        ("1", [1], "陶豆"),
        ("2", [2], "陶壶"),
    ]


def test_parenthesised_artifact_id_and_grouped_seq():
    items = parse_note("1、2. 陶豆（M4:2、M4:1）")
    assert len(items) == 1
    item = items[0]
    assert item.seq == "1、2"
    assert item.seq_list == [1, 2]
    assert item.name == "陶豆"
    assert item.artifact_ids == ["M4:2", "M4:1"]


def test_single_artifact_in_parentheses():
    item = parse_note("1. 骨笄（M4:1）")[0]
    assert item.name == "骨笄"
    assert item.artifact_ids == ["M4:1"]


def test_range_seq_expands_and_keeps_id_order():
    item = parse_note("1～4.豆（M3：4、M3：2、M3：3、M3：1）")[0]
    assert item.seq == "1～4"
    assert item.seq_list == [1, 2, 3, 4]
    assert item.name == "豆"
    assert item.artifact_ids == ["M3:4", "M3:2", "M3:3", "M3:1"]


def test_grouped_range_seq_expands_including_disjoint_number():
    item = parse_note("3～5、9. 陶豆")[0]
    assert item.seq == "3～5、9"
    assert item.seq_list == [3, 4, 5, 9]
    assert item.name == "陶豆"
    assert item.artifact_ids == []


def test_letter_seq_is_kept_with_empty_seq_list():
    item = parse_note("A. 盗坑（长沙青振）")[0]
    assert item.seq == "A"
    assert item.seq_list == []
    assert item.name == "盗坑"
    assert item.artifact_ids == []


def test_circled_seq_maps_to_arabic_number():
    items = parse_note("①骨笄（M4:1） ②陶豆（M4:2）")
    assert [(i.seq, i.seq_list, i.name, i.artifact_ids) for i in items] == [
        ("1", [1], "骨笄", ["M4:1"]),
        ("2", [2], "陶豆", ["M4:2"]),
    ]


def test_circled_group_accumulates_into_one_clause():
    items = parse_note("①、②. 陶豆（M4:2、M4:1）")
    assert len(items) == 1
    assert items[0].seq == "1、2"
    assert items[0].seq_list == [1, 2]
    assert items[0].artifact_ids == ["M4:2", "M4:1"]


def test_tex_range_form_and_following_clause():
    items = parse_note("$1\\sim 4$ 陶豆 5.陶壶")
    assert len(items) == 2
    assert items[0].seq == "1～4"
    assert items[0].seq_list == [1, 2, 3, 4]
    assert items[0].artifact_ids == []
    assert items[1].seq == "5"
    assert items[1].seq_list == [5]
    assert items[1].name == "陶壶"


def test_glued_artifact_id_without_space():
    item = parse_note("1.00FBG1:2")[0]
    assert item.seq == "1"
    assert item.seq_list == [1]
    assert item.artifact_ids == ["00FBG1:2"]


def test_clause_may_have_no_artifact_id():
    item = parse_note("3～7. 陶豆")[0]
    assert item.seq == "3～7"
    assert item.seq_list == [3, 4, 5, 6, 7]
    assert item.name == "陶豆"
    assert item.artifact_ids == []


def test_newline_merged_note_segments_parse_as_clauses():
    items = parse_note("1. 陶豆（M4:1）\n2. 陶壶（M4:2）")
    assert [(i.seq, i.artifact_ids) for i in items] == [
        ("1", ["M4:1"]),
        ("2", ["M4:2"]),
    ]


@pytest.mark.parametrize("text", ["", "   ", "0 8厘米", "这段说明没有序号也没有器物号。"])
def test_scale_noise_and_text_without_clauses_yield_no_items(text):
    assert parse_note(text) == []


def test_caption_fallback_extracts_title_artifacts():
    assert extract_caption_artifacts("图2-1-16 M4出土铜舟（M4:2）") == ["M4:2"]
    assert extract_caption_artifacts("图一三 M9出土器物（M9:6、M9:4）") == ["M9:6", "M9:4"]
    assert extract_caption_artifacts("图二四七 M43出土器物（M43:75a）") == ["M43:75a"]


@pytest.mark.parametrize("caption", [None, "", "图版204", "图二一二 铜舟"])
def test_caption_without_artifacts_is_empty(caption):
    assert extract_caption_artifacts(caption) == []
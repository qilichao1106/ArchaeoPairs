"""T-007 group_views: one group per seq, unlabeled views reported separately.

Frozen expectations (card §2):

* all views sharing a ``seq_id`` -> one ViewGroup;
* views with no binding -> ``unbound_views``;
* ``all_unlabeled_rule_b`` only when no label bound anywhere -> one group with
  ``seq_ids=[]`` over every view;
* ``view_ids`` keep the input reading order.
"""

from __future__ import annotations

from archaeopairs.mapping import group_views
from archaeopairs.models import ViewBinding

from t007_synthetic import make_view


def _binding(view_id: int, seq_id: str | None) -> ViewBinding:
    return ViewBinding(view_id=view_id, seq_id=seq_id, method="inside")


def _three_views():
    return [
        make_view(0, (0, 0, 10, 10)),
        make_view(1, (20, 0, 30, 10)),
        make_view(2, (40, 0, 50, 10)),
    ]


def test_same_seq_views_form_one_group() -> None:
    groups, unbound = group_views(
        _three_views(), [_binding(0, "1"), _binding(1, "1"), _binding(2, "2")]
    )

    assert len(groups) == 2
    by_seq = {group.seq_ids[0]: group for group in groups}
    assert by_seq["1"].view_ids == [0, 1]
    assert by_seq["2"].view_ids == [2]
    assert [group.group_id for group in groups] == [0, 1]
    assert unbound == []


def test_different_seqs_are_separate_groups() -> None:
    groups, unbound = group_views(
        _three_views(), [_binding(0, "1"), _binding(1, "2"), _binding(2, "3")]
    )

    assert [group.seq_ids for group in groups] == [["1"], ["2"], ["3"]]
    assert unbound == []


def test_negative_unlabeled_views_are_reported_not_grouped() -> None:
    groups, unbound = group_views(_three_views(), [_binding(0, "1")])

    assert len(groups) == 1
    assert groups[0].view_ids == [0]
    assert unbound == [
        {"view_ids": [1], "reason": "no_seq"},
        {"view_ids": [2], "reason": "no_seq"},
    ]


def test_all_unlabeled_rule_b_group_covers_every_view() -> None:
    groups, unbound = group_views(
        _three_views(), [], all_unlabeled_rule_b=True
    )

    assert len(groups) == 1
    assert groups[0].group_id == 0
    assert groups[0].view_ids == [0, 1, 2]
    assert groups[0].seq_ids == []
    assert groups[0].evidence.get("rule") == "all_unlabeled_rule_b"
    assert unbound == []


def test_negative_all_unlabeled_without_rule_b_has_no_group() -> None:
    groups, unbound = group_views(_three_views(), [], all_unlabeled_rule_b=False)

    assert groups == []
    assert [item["view_ids"] for item in unbound] == [[0], [1], [2]]
    assert all(item["reason"] == "no_seq" for item in unbound)


def test_negative_rule_b_is_not_used_when_one_label_exists() -> None:
    groups, unbound = group_views(
        _three_views(), [_binding(0, "1")], all_unlabeled_rule_b=True
    )

    assert [group.seq_ids for group in groups] == [["1"]]
    assert [item["view_ids"] for item in unbound] == [[1], [2]]


def test_negative_binding_to_unknown_view_is_ignored() -> None:
    groups, unbound = group_views(_three_views(), [_binding(99, "1")])

    assert groups == []
    assert [item["view_ids"] for item in unbound] == [[0], [1], [2]]


def test_view_ids_follow_input_reading_order() -> None:
    views = [make_view(7, (0, 0, 10, 10)), make_view(2, (20, 0, 30, 10))]

    groups, _ = group_views(views, [_binding(7, "1"), _binding(2, "1")])

    assert groups[0].view_ids == [7, 2]


def test_duplicate_binding_does_not_duplicate_view_id() -> None:
    views = [make_view(0, (0, 0, 10, 10))]

    groups, _ = group_views(views, [_binding(0, "1"), _binding(0, "1")])

    assert groups[0].view_ids == [0]


def test_empty_views_yield_no_groups() -> None:
    groups, unbound = group_views([], [], all_unlabeled_rule_b=True)

    assert groups == []
    assert unbound == []
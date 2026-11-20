"""T-007 bind_labels_to_views: strictly spatial, never distance-guessed.

Frozen expectations (card §2):

* a label's bbox centre binds to the view bbox that contains it;
* several containing views -> the one with the smallest bbox area;
* no containing view -> an ``unbound`` binding at ``view_id=-1``;
* one view may collect several seq labels; group labels are skipped.
"""

from __future__ import annotations

from archaeopairs.mapping import bind_labels_to_views

from t007_synthetic import make_label, make_view


def test_centre_inside_one_view_binds_inside() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    bindings = bind_labels_to_views(views, [make_label("1.", 50, 50)])

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.view_id == 0
    assert binding.seq_id == "1"
    assert binding.method == "inside"
    assert binding.confidence == 1.0


def test_multiple_containing_views_pick_smallest_bbox_area() -> None:
    views = [
        make_view(0, (0, 0, 300, 300)),      # 90_000 px
        make_view(1, (80, 80, 120, 120)),    #  1_600 px (smallest)
        make_view(2, (40, 40, 260, 260)),    # 48_400 px
    ]

    bindings = bind_labels_to_views(views, [make_label("2", 100, 100)])

    assert len(bindings) == 1
    assert bindings[0].view_id == 1
    assert bindings[0].seq_id == "2"
    assert bindings[0].method == "smallest_containing"
    assert bindings[0].confidence == 0.9


def test_same_view_accepts_several_seq_labels() -> None:
    views = [make_view(0, (0, 0, 100, 100))]
    labels = [make_label("1", 20, 20), make_label("3", 80, 80)]

    bindings = bind_labels_to_views(views, labels)

    assert [(b.view_id, b.seq_id) for b in bindings] == [(0, "1"), (0, "3")]
    assert all(b.method == "inside" for b in bindings)


def test_negative_no_containing_view_is_unbound_not_guessed() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    bindings = bind_labels_to_views(views, [make_label("9", 500, 500)])

    assert len(bindings) == 1
    assert bindings[0].view_id == -1
    assert bindings[0].seq_id == "9"
    assert bindings[0].method == "unbound"
    assert bindings[0].confidence == 0.0


def test_label_just_outside_binds_to_nearest_view_within_gap() -> None:
    """Printed labels sit just outside the drawing; R-SEQ-03 allows 'nearby'.

    The 60px threshold is a label-to-drawing attachment only; artifact/scale
    matching never uses distance.
    """
    views = [make_view(0, (0, 0, 100, 100))]

    bindings = bind_labels_to_views(views, [make_label("2", 101, 50)])

    assert bindings[0].view_id == 0
    assert bindings[0].method == "nearest"
    assert bindings[0].confidence == 0.7


def test_negative_far_label_stays_unbound() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    bindings = bind_labels_to_views(views, [make_label("2", 300, 300)])

    assert bindings[0].view_id == -1
    assert bindings[0].method == "unbound"


def test_negative_group_label_is_skipped_not_bound() -> None:
    views = [make_view(0, (0, 0, 100, 100))]
    labels = [make_label("2、3", 50, 50), make_label("1", 20, 20)]

    bindings = bind_labels_to_views(views, labels)

    assert len(bindings) == 1
    assert (bindings[0].view_id, bindings[0].seq_id) == (0, "1")


def test_negative_no_labels_yield_no_bindings() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    assert bind_labels_to_views(views, []) == []
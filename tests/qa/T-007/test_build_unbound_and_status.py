"""T-007 build_artifact_map: unbound ledgers, status and conflict propagation.

Frozen expectations (card §3, R-MAP-05):

* unresolved groups/views/seqs are recorded in the three ``unbound_*`` lists,
  never silently dropped;
* a group whose seqs have no artifact id -> ``unbound_groups``;
* a mapping seq with no view -> ``unbound_seqs``; an OCR label outside every
  view is also reported;
* rule-B with no caption id -> ``unbound_groups``;
* status is ``composed`` only when there are units and no conflicts/alarms,
  otherwise ``pending_review``;
* text-mapping conflicts are merged and de-duplicated.
"""

from __future__ import annotations

from t007_synthetic import build_map, make_label, make_mapping, make_view


def test_build_reports_unbound_view_and_unbound_seqs() -> None:
    views = [
        make_view(0, (0, 0, 10, 10)),
        make_view(1, (20, 0, 30, 10)),
        make_view(2, (40, 0, 50, 10)),
    ]
    labels = [
        make_label("1", 5, 5),
        make_label("2", 25, 5),
        make_label("9", 500, 500),  # centre outside every view
    ]
    mapping = make_mapping(
        {"1": ["A:1"], "2": ["A:2"], "3": ["A:3"]}
    )

    amap = build_map(views, labels, mapping)

    assert {unit.artifact_id for unit in amap.units} == {"A:1", "A:2"}
    assert amap.unbound_views == [{"view_ids": [2], "reason": "no_seq"}]

    unbound = {item["seq_id"]: item for item in amap.unbound_seqs}
    assert set(unbound) == {"3", "9"}
    assert unbound["3"]["reason"] == "no_view"
    assert unbound["3"]["artifact_ids"] == ["A:3"]
    assert unbound["9"]["reason"] == "no_view"
    assert unbound["9"]["artifact_ids"] == []
    assert amap.conflicts == []
    assert amap.alarms == []
    assert amap.status == "composed"


def test_negative_build_group_without_artifact_is_unbound_group() -> None:
    views = [make_view(0, (0, 0, 10, 10))]

    amap = build_map(
        views, [make_label("1", 5, 5)], make_mapping({"1": []})
    )

    assert amap.units == []
    assert amap.unbound_groups == [
        {
            "group_id": 0,
            "view_ids": [0],
            "seq_id": "1",
            "reason": "unmapped_seq",
        }
    ]
    assert amap.unbound_views == []
    assert amap.unbound_seqs == []
    assert amap.status == "pending_review"


def test_negative_build_rule_b_without_caption_is_unbound_group() -> None:
    views = [
        make_view(0, (0, 0, 50, 50)),
        make_view(1, (60, 0, 110, 50)),
    ]

    amap = build_map(
        views,
        [],
        make_mapping(caption_artifacts=[], case_type="seq_missing"),
        all_unlabeled_rule_b=True,
    )

    assert amap.units == []
    assert amap.unbound_groups == [
        {
            "group_id": 0,
            "view_ids": [0, 1],
            "seq_id": None,
            "reason": "no_seq",
        }
    ]
    assert amap.unbound_views == []
    assert amap.status == "pending_review"


def test_build_text_mapping_conflicts_force_pending_review() -> None:
    views = [make_view(0, (0, 0, 10, 10))]

    amap = build_map(
        views,
        [make_label("1", 5, 5)],
        make_mapping(
            {"1": ["A:1"]}, conflicts=["artifact_claimed:x"]
        ),
    )

    assert len(amap.units) == 1
    assert amap.conflicts == ["artifact_claimed:x"]
    assert amap.status == "pending_review"


def test_negative_build_without_views_has_no_units_and_needs_review() -> None:
    amap = build_map([], [], make_mapping({}, case_type="seq_missing"))

    assert amap.units == []
    assert amap.unbound_groups == []
    assert amap.unbound_views == []
    assert amap.unbound_seqs == []
    assert amap.conflicts == []
    assert amap.alarms == []
    assert amap.status == "pending_review"
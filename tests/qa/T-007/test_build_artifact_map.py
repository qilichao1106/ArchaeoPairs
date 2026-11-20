"""T-007 build_artifact_map: the four cardinalities and cross-group rules.

Frozen expectations (card §3, R-MAP-02/03/06/07/08):

* 1 seq : 1 art -> one unit on its view;
* N seq : 1 art -> one ``rule_b`` unit merging all the group's views;
* 1 seq : N art -> N units sharing the group's views (``split_same_seq``);
* N seq : N art -> each seq's artifact stays with that seq's view;
* the same artifact in several groups merges only when every holder declares
  just that artifact, otherwise ``cross_group_artifact:<id>`` is a conflict and
  the units are kept separate;
* rule-B unlabeled figure: one unique caption artifact -> one unit; several
  caption artifacts -> ``caption_multi_artifact`` conflict, no guessed unit.
"""

from __future__ import annotations

from archaeopairs.models import ArtifactMap, ArtifactUnit

from t007_synthetic import build_map, make_label, make_mapping, make_view


def _two_views():
    return [
        make_view(0, (0, 0, 10, 10)),
        make_view(1, (20, 0, 30, 10)),
    ]


def test_build_one_seq_one_artifact() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    amap = build_map(
        views,
        [make_label("1.", 50, 50)],
        make_mapping({"1": ["M4:1"]}, case_type="rule_a"),
    )

    assert isinstance(amap, ArtifactMap)
    assert len(amap.units) == 1
    unit = amap.units[0]
    assert isinstance(unit, ArtifactUnit)
    assert unit.artifact_id == "M4:1"
    assert unit.seq_ids == ["1"]
    assert unit.view_ids == [0]
    assert unit.group_ids == [0]
    assert unit.source == "figure_note"
    assert 0.0 < unit.confidence <= 1.0
    assert unit.status == "output"
    assert unit.scale_bindings == []
    assert amap.case_type == "rule_a"
    assert amap.status == "composed"
    assert amap.conflicts == []
    assert amap.alarms == []
    assert amap.unbound_groups == []
    assert amap.unbound_views == []
    assert amap.unbound_seqs == []


def test_build_n_seq_one_artifact_is_rule_b() -> None:
    views = _two_views()
    labels = [
        make_label("4", 5, 5),
        make_label("6", 25, 5),
        make_label("7", 25, 6),
    ]

    amap = build_map(
        views,
        labels,
        make_mapping(
            {"4": ["M1:29"], "6": ["M1:29"], "7": ["M1:29"]},
            case_type="rule_b",
        ),
    )

    assert len(amap.units) == 1
    unit = amap.units[0]
    assert unit.artifact_id == "M1:29"
    assert unit.seq_ids == ["4", "6", "7"]
    assert unit.view_ids == [0, 1]
    assert unit.group_ids == [0, 1, 2]
    assert unit.case == "rule_b"
    assert unit.whole_image is True
    assert 0.0 < unit.confidence <= 1.0
    assert amap.conflicts == []
    assert amap.status == "composed"


def test_build_one_seq_n_artifacts_share_the_same_view() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    amap = build_map(
        views,
        [make_label("8.", 50, 50)],
        make_mapping(
            {"8": ["M139:3", "M139:26"]}, case_type="split_same_seq"
        ),
    )

    assert [unit.artifact_id for unit in amap.units] == ["M139:3", "M139:26"]
    for unit in amap.units:
        assert unit.seq_ids == ["8"]
        assert unit.view_ids == [0]
        assert unit.group_ids == [0]
        assert unit.case == "split_same_seq"
        assert 0.0 < unit.confidence <= 1.0
        assert unit.evidence.get("shared_group") is True
        assert unit.scale_bindings == []
    assert amap.status == "composed"
    assert amap.conflicts == []


def test_build_n_seq_n_artifacts_keep_positional_correspondence() -> None:
    views = _two_views()
    # Labels arrive out of reading order on purpose: each artifact must follow
    # its own seq's view, never a label-order zip.
    labels = [make_label("2", 25, 5), make_label("1", 5, 5)]

    amap = build_map(
        views,
        labels,
        make_mapping(
            {"1": ["M4:2"], "2": ["M4:1"]}, case_type="rule_a"
        ),
    )

    by_artifact = {unit.artifact_id: unit for unit in amap.units}
    assert set(by_artifact) == {"M4:1", "M4:2"}
    assert by_artifact["M4:2"].seq_ids == ["1"]
    assert by_artifact["M4:2"].view_ids == [0]
    assert by_artifact["M4:1"].seq_ids == ["2"]
    assert by_artifact["M4:1"].view_ids == [1]
    assert amap.status == "composed"


def test_build_cross_group_single_artifact_merges() -> None:
    views = _two_views()

    amap = build_map(
        views,
        [make_label("1", 5, 5), make_label("2", 25, 5)],
        make_mapping(
            {"1": ["M5:1"], "2": ["M5:1"]}, case_type="rule_b"
        ),
    )

    assert len(amap.units) == 1
    unit = amap.units[0]
    assert unit.artifact_id == "M5:1"
    assert unit.seq_ids == ["1", "2"]
    assert unit.view_ids == [0, 1]
    assert unit.group_ids == [0, 1]
    assert unit.case == "rule_b"
    assert unit.whole_image is True
    assert amap.conflicts == []
    assert amap.status == "composed"


def test_negative_build_cross_group_artifact_conflict_keeps_units_unmerged() -> None:
    views = _two_views()

    amap = build_map(
        views,
        [make_label("1", 5, 5), make_label("2", 25, 5)],
        make_mapping(
            {"1": ["M5:1"], "2": ["M5:1", "M5:2"]}, case_type="rule_a"
        ),
    )

    conflict = "cross_group_artifact:M5:1"
    assert conflict in amap.conflicts
    assert amap.conflicts.count(conflict) == 1

    kept = [unit for unit in amap.units if unit.artifact_id == "M5:1"]
    assert len(kept) == 2, "conflicting artifact must not be merged"
    assert {tuple(unit.group_ids) for unit in kept} == {(0,), (1,)}
    assert all(unit.status == "review" for unit in kept)

    other = [unit for unit in amap.units if unit.artifact_id == "M5:2"]
    assert len(other) == 1
    assert other[0].status == "output"
    assert amap.status == "pending_review"


def test_build_rule_b_caption_unique_makes_one_unit() -> None:
    views = [
        make_view(0, (0, 0, 50, 50)),
        make_view(1, (60, 0, 110, 50)),
    ]

    amap = build_map(
        views,
        [],
        make_mapping(caption_artifacts=["M7:1"], case_type="seq_missing"),
        all_unlabeled_rule_b=True,
    )

    assert len(amap.units) == 1
    unit = amap.units[0]
    assert unit.artifact_id == "M7:1"
    assert unit.seq_ids == []
    assert unit.view_ids == [0, 1]
    assert unit.group_ids == [0]
    assert unit.case == "rule_b"
    assert unit.source == "caption"
    assert unit.confidence == 0.8
    assert unit.whole_image is True
    assert amap.status == "composed"
    assert amap.unbound_groups == []
    assert amap.unbound_views == []
    assert amap.unbound_seqs == []
    assert amap.conflicts == []


def test_build_rule_b_caption_duplicates_are_unique() -> None:
    views = [make_view(0, (0, 0, 50, 50))]

    amap = build_map(
        views,
        [],
        make_mapping(
            caption_artifacts=["M7:1", "M7:1"], case_type="seq_missing"
        ),
        all_unlabeled_rule_b=True,
    )

    assert [unit.artifact_id for unit in amap.units] == ["M7:1"]
    assert amap.conflicts == []
    assert amap.status == "composed"


def test_negative_build_caption_multi_artifact_is_a_conflict() -> None:
    views = _two_views()

    amap = build_map(
        views,
        [],
        make_mapping(
            caption_artifacts=["M7:1", "M7:2"], case_type="seq_missing"
        ),
        all_unlabeled_rule_b=True,
    )

    assert amap.units == [], "multiple caption ids must not be guessed"
    assert any(
        conflict.startswith("caption_multi_artifact:")
        for conflict in amap.conflicts
    )
    assert amap.status == "pending_review"
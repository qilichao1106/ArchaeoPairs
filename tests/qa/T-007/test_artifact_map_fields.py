"""T-007 ArtifactMap / ArtifactUnit fields and the T-008 scale hand-off.

Frozen expectations (card §1/§3):

* ArtifactMap exposes book_id, figure_id, line, case_type, units,
  unbound_groups, unbound_views, unbound_seqs, conflicts, alarms, status;
* ArtifactUnit exposes artifact_id, artifact_name, seq_ids, view_ids,
  group_ids, scale_bindings, line, case, source, confidence, whole_image,
  status, evidence;
* scale binding is out of scope for T-007: every ``scale_bindings`` list is
  empty and every unit carries the requested line.
"""

from __future__ import annotations

from t007_synthetic import build_map, make_label, make_mapping, make_view


ARTIFACT_MAP_FIELDS = {
    "book_id",
    "figure_id",
    "line",
    "case_type",
    "units",
    "unbound_groups",
    "unbound_views",
    "unbound_seqs",
    "conflicts",
    "alarms",
    "status",
}

ARTIFACT_UNIT_FIELDS = {
    "artifact_id",
    "artifact_name",
    "seq_ids",
    "view_ids",
    "group_ids",
    "scale_bindings",
    "line",
    "case",
    "source",
    "confidence",
    "whole_image",
    "status",
    "evidence",
}


def test_artifact_map_and_unit_fields_are_complete() -> None:
    views = [
        make_view(0, (0, 0, 10, 10)),
        make_view(1, (20, 0, 30, 10)),
    ]
    mapping = make_mapping(
        {"1": ["M5:1"], "2": ["M5:1"]}, case_type="rule_b"
    )

    amap = build_map(
        views,
        [make_label("1", 5, 5), make_label("2", 25, 5)],
        mapping,
        book_id="book-001",
        figure_id="fig-2-1-16",
        line="single_line",
    )

    payload = amap.model_dump()
    assert ARTIFACT_MAP_FIELDS <= set(payload)
    assert payload["book_id"] == "book-001"
    assert payload["figure_id"] == "fig-2-1-16"
    assert payload["line"] == "single_line"
    assert payload["case_type"] == "rule_b"
    assert payload["alarms"] == []
    assert payload["status"] == "composed"

    assert len(payload["units"]) == 1
    unit = payload["units"][0]
    assert ARTIFACT_UNIT_FIELDS <= set(unit)
    assert unit["artifact_id"] == "M5:1"
    assert unit["artifact_name"] is None
    assert unit["seq_ids"] == ["1", "2"]
    assert unit["view_ids"] == [0, 1]
    assert unit["group_ids"] == [0, 1]
    assert unit["scale_bindings"] == []
    assert unit["line"] == "single_line"
    assert unit["case"] == "rule_b"
    assert unit["source"] == "figure_note"
    assert 0.0 < unit["confidence"] <= 1.0
    assert unit["whole_image"] is True
    assert unit["status"] == "output"
    assert isinstance(unit["evidence"], dict)


def test_every_unit_keeps_scale_bindings_empty() -> None:
    views = [make_view(0, (0, 0, 100, 100))]

    amap = build_map(
        views,
        [make_label("8", 50, 50)],
        make_mapping(
            {"8": ["M139:3", "M139:26"]}, case_type="split_same_seq"
        ),
        line="single_line",
    )

    assert len(amap.units) == 2
    for unit in amap.units:
        assert unit.scale_bindings == []
        assert unit.line == "single_line"
    assert all(
        payload["scale_bindings"] == []
        for payload in amap.model_dump()["units"]
    )


def test_build_defaults_line_to_multi_line() -> None:
    views = [make_view(0, (0, 0, 10, 10))]

    amap = build_map(
        views,
        [make_label("1", 5, 5)],
        make_mapping({"1": ["A:1"]}),
    )

    assert amap.line == "multi_line"
    assert amap.units[0].line == "multi_line"
"""T-008 apply_scale_bindings: group union, scale_id de-duplication, review.

Frozen expectations (card §3 / scales.py):

* a unit collects the bindings of every group in its ``group_ids`` (union,
  first occurrence per ``scale_id`` wins);
* ``unit.scale_bindings`` is a list of ``ScaleBinding`` dicts;
* a unit with no bar becomes ``status="review"``, adds
  ``group_no_scale:<group_id>`` and is never dropped;
* the input ``ArtifactMap`` is not mutated (deep copy returned).
"""

from __future__ import annotations

from archaeopairs.mapping import apply_scale_bindings, bind_scales

from t008_synthetic import make_group, make_map, make_scale, make_unit, scale_ids


def _binding_ids(unit) -> list[int]:
    return [binding["scale_id"] for binding in unit.scale_bindings]


def test_apply_unions_bindings_across_group_ids_in_unit_order() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"]), make_group(2, ["3"])]
    scales = [make_scale("1.", ["1"]), make_scale("2.", ["2"])]
    bound, _, _ = bind_scales(groups, scales)
    target = make_map([
        make_unit("A:1", [0, 1]),
        make_unit("A:2", [1, 0]),
        make_unit("A:3", [2]),
    ])

    out = apply_scale_bindings(target, bound)

    assert _binding_ids(out.units[0]) == [0, 1]
    assert _binding_ids(out.units[1]) == [1, 0]
    assert _binding_ids(out.units[2]) == []
    assert [unit.status for unit in out.units] == ["output", "output", "review"]
    assert out.conflicts == ["group_no_scale:2"]
    assert len(out.units) == 3

    payload = out.units[0].scale_bindings[0]
    assert isinstance(payload, dict)
    assert set(payload) == {
        "scale_id", "source", "shared", "text",
        "value", "unit", "prefix_nos",
    }
    assert payload["source"] == "L1_prefix"
    assert payload["text"] == "1."


def test_apply_deduplicates_the_same_scale_id_across_groups() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"])]
    scales = [make_scale("1～2.", ["1", "2"])]
    bound, _, _ = bind_scales(groups, scales)
    assert [scale_ids(items) for items in bound] == [[0], [0]]

    target = make_map([make_unit("A:1", [0, 1, 0, 1])])

    out = apply_scale_bindings(target, bound)

    assert _binding_ids(out.units[0]) == [0]
    assert out.units[0].status == "output"
    assert out.conflicts == []


def test_apply_bar_less_unit_goes_to_review_with_evidence() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"])]
    bound, _, _ = bind_scales(groups, [make_scale("1.", ["1"])])
    target = make_map(
        [make_unit("A:1", [0]), make_unit("A:2", [1]), make_unit("A:3", [1])],
        conflicts=["keep:me", "group_no_scale:1"],
        alarms=["E004"],
    )

    out = apply_scale_bindings(target, bound)

    assert [unit.status for unit in out.units] == ["output", "review", "review"]
    assert _binding_ids(out.units[0]) == [0]
    assert out.units[1].scale_bindings == []
    assert out.conflicts == ["keep:me", "group_no_scale:1"]
    assert out.conflicts.count("group_no_scale:1") == 1
    assert out.alarms == ["E004"]
    assert len(out.units) == 3, "bar-less units must be kept"

    # The input map keeps its own statuses/conflicts.
    assert target.units[1].status == "output"
    assert target.conflicts == ["keep:me", "group_no_scale:1"]


def test_apply_returns_a_deep_copy_and_does_not_mutate_input() -> None:
    groups = [make_group(0, ["1"])]
    bound, _, _ = bind_scales(groups, [make_scale("1.", ["1"])])
    target = make_map(
        [make_unit("A:1", [0])], conflicts=["keep:me"], alarms=["E004"]
    )
    snapshot = target.model_dump()

    out = apply_scale_bindings(target, bound)

    assert out is not target
    assert out.units[0] is not target.units[0]
    assert target.model_dump() == snapshot
    assert out.units[0].status == "output"

    out.units[0].status = "review"
    out.units[0].scale_bindings.clear()
    out.conflicts.append("mutated")
    out.alarms.append("E007")

    assert target.model_dump() == snapshot, "mutating the copy must not touch input"


def test_apply_unit_with_one_empty_group_is_bound_not_reviewed() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"])]
    bound, _, _ = bind_scales(groups, [make_scale("1.", ["1"])])
    assert bound[1] == []
    target = make_map([make_unit("A:1", [0, 1])])

    out = apply_scale_bindings(target, bound)

    assert _binding_ids(out.units[0]) == [0]
    assert out.units[0].status == "output"
    assert out.conflicts == []
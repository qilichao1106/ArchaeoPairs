"""T-008 negative controls: failures must be reported, never guessed.

Covered negative expectations:

* L1 wins over L2: a single bar with a prefix does not leak to other groups;
* L3: a bar without prefixes among >=2 bars is abandoned (E004), never bound
  by pixel distance, while the numbered bar still binds by prefix;
* E004 is emitted once per figure even with several unnumbered bars;
* a group with no bar emits E007 + ``group_no_scale:<id>`` (no silent gap);
* a figure with no bar at all reports every group;
* a numbered bar matching no group is not marked abandoned;
* blank/whitespace prefixes are unnumbered under L3;
* apply ignores out-of-range group ids and sends bar-less units to review.
"""

from __future__ import annotations

from archaeopairs.mapping import apply_scale_bindings, bind_scales

from t008_synthetic import (
    make_group,
    make_map,
    make_scale,
    make_unit,
    scale_ids,
)


def test_negative_l1_does_not_fall_back_to_l2_for_unmatched_group() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"])]
    # Exactly one bar exists, but it is numbered: L1 must win, so group 1
    # must NOT receive the L2 shared copy.
    scales = [make_scale("1.", ["1"])]

    bound, records, alarms = bind_scales(groups, scales)

    assert scale_ids(bound[0]) == [0]
    assert bound[0][0].source == "L1_prefix"
    assert bound[0][0].shared is False
    assert bound[1] == []
    assert records[0]["source"] == "L1_prefix"
    assert "E007" in alarms
    assert alarms.count("E007") == 1
    assert "group_no_scale:1" in alarms
    assert "group_no_scale:0" not in alarms
    assert "E004" not in alarms
    assert not any(
        binding.source == "L2_unique_shared"
        for items in bound
        for binding in items
    )


def test_negative_l3_unnumbered_bar_is_abandoned_not_distance_bound() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["3"])]
    scales = [
        make_scale("1.", ["1"], bbox=(0, 0, 20, 8)),
        # No prefix at all; bbox is deliberately near group 1's view area,
        # which must still be irrelevant (no coordinate inference).
        make_scale("0—4", [], bbox=(40, 200, 80, 208)),
    ]

    bound, records, alarms = bind_scales(groups, scales)

    assert scale_ids(bound[0]) == [0]
    assert bound[0][0].source == "L1_prefix"
    assert bound[1] == []
    assert records[0]["abandoned"] is False
    assert records[0]["source"] == "L1_prefix"
    assert records[1]["abandoned"] is True
    assert records[1]["source"] is None
    assert records[1]["text"] == "0—4"
    assert records[1]["bbox"] == [40, 200, 80, 208]
    assert alarms.count("E004") == 1
    assert "E007" in alarms
    assert "group_no_scale:1" in alarms
    assert all(
        binding.scale_id != 1 for items in bound for binding in items
    ), "abandoned bar must never be bound"


def test_negative_l3_several_unnumbered_bars_raise_e004_once() -> None:
    groups = [make_group(0, ["1"])]
    scales = [make_scale("0—4", []), make_scale("0—10", [])]

    bound, records, alarms = bind_scales(groups, scales)

    assert bound == [[]]
    assert [record["abandoned"] for record in records] == [True, True]
    assert [record["source"] for record in records] == [None, None]
    assert alarms.count("E004") == 1
    assert "E007" in alarms
    assert "group_no_scale:0" in alarms


def test_negative_group_without_scale_is_reported_not_silent() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"])]
    scales = [make_scale("1.", ["1"])]

    bound, _, alarms = bind_scales(groups, scales)

    assert bound[1] == []
    assert "E007" in alarms
    assert alarms.count("E007") == 1
    assert "group_no_scale:1" in alarms
    assert "group_no_scale:0" not in alarms


def test_negative_figure_without_any_bar_reports_every_group() -> None:
    groups = [make_group(0, ["1"]), make_group(1, ["2"])]

    bound, records, alarms = bind_scales(groups, [])

    assert bound == [[], []]
    assert records == []
    assert "E007" in alarms
    assert alarms.count("E007") == 1
    assert "group_no_scale:0" in alarms
    assert "group_no_scale:1" in alarms
    assert "E004" not in alarms
    assert len(alarms) == len(set(alarms))


def test_negative_numbered_bar_matching_no_group_is_not_abandoned() -> None:
    groups = [make_group(0, ["1"])]
    scales = [make_scale("1.", ["1"]), make_scale("9.", ["9"])]

    bound, records, alarms = bind_scales(groups, scales)

    assert scale_ids(bound[0]) == [0]
    assert records[1]["abandoned"] is False
    assert "E004" not in alarms
    assert alarms == []


def test_negative_blank_prefixes_are_unnumbered_under_l3() -> None:
    groups = [make_group(0, ["1"])]
    scales = [make_scale("1.", ["1"]), make_scale("—", ["  ", ""])]

    bound, records, alarms = bind_scales(groups, scales)

    assert scale_ids(bound[0]) == [0]
    assert records[1]["prefix_nos"] == []
    assert records[1]["abandoned"] is True
    assert records[1]["source"] is None
    assert alarms.count("E004") == 1


def test_negative_apply_out_of_range_group_id_is_ignored() -> None:
    groups = [make_group(0, ["1"])]
    bound, _, _ = bind_scales(groups, [make_scale("1.", ["1"])])
    target = make_map([
        make_unit("A:far", [99]),
        make_unit("A:mixed", [0, 99]),
    ])

    out = apply_scale_bindings(target, bound)

    assert out.units[0].status == "review"
    assert out.units[0].scale_bindings == []
    assert out.units[1].status == "output"
    assert [b["scale_id"] for b in out.units[1].scale_bindings] == [0]
    assert "group_no_scale:99" in out.conflicts
    assert out.conflicts.count("group_no_scale:99") == 1
    assert len(out.units) == 2, "out-of-range group id must not drop units"


def test_negative_apply_unit_without_group_ids_goes_to_review() -> None:
    groups = [make_group(0, ["1"])]
    bound, _, _ = bind_scales(groups, [make_scale("1.", ["1"])])
    target = make_map([make_unit("A:orphan", [])])

    out = apply_scale_bindings(target, bound)

    assert out.units[0].scale_bindings == []
    assert out.units[0].status == "review"
    assert out.conflicts == []
    assert len(out.units) == 1
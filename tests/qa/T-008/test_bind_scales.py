"""T-008 L1 prefix hard binding and L2 unique-bar sharing.

Frozen expectations (card §2 / scales.py):

* L1: ``ScaleBar.prefix_nos`` intersecting ``ViewGroup.seq_ids`` binds that
  group with ``source="L1_prefix"``; one bar may bind several groups.
* ``shared`` is true for a multi-prefix bar or a multi-seq group.
* L2: exactly one bar and no L1 binding -> every group gets a copy with
  ``source="L2_unique_shared"`` and ``shared=True``.
* ``scale_records`` has one entry per bar with the frozen field set.
"""

from __future__ import annotations

from archaeopairs.mapping import bind_scales

from t008_synthetic import make_group, make_scale, scale_ids, sources


def test_l1_single_prefix_binds_single_group() -> None:
    groups = [make_group(0, ["1"])]
    scales = [make_scale("1.", ["1"], value=0.5, unit="cm")]

    bound, records, alarms = bind_scales(groups, scales)

    assert len(bound) == 1
    assert len(bound[0]) == 1
    binding = bound[0][0]
    assert binding.scale_id == 0
    assert binding.source == "L1_prefix"
    assert binding.shared is False
    assert binding.text == "1."
    assert binding.value == 0.5
    assert binding.unit == "cm"
    assert binding.prefix_nos == ["1"]
    assert alarms == []
    assert records[0]["source"] == "L1_prefix"
    assert records[0]["abandoned"] is False


def test_l1_one_bar_binds_every_matching_group() -> None:
    groups = [
        make_group(0, ["1"]),
        make_group(1, ["2"]),
        make_group(2, ["3"]),
    ]
    scales = [make_scale("1～3.", ["1", "2", "3"])]

    bound, records, alarms = bind_scales(groups, scales)

    assert [len(items) for items in bound] == [1, 1, 1]
    assert [scale_ids(items) for items in bound] == [[0], [0], [0]]
    assert [sources(items) for items in bound] == [
        ["L1_prefix"], ["L1_prefix"], ["L1_prefix"],
    ]
    assert all(items[0].shared is True for items in bound)
    assert all(items[0].prefix_nos == ["1", "2", "3"] for items in bound)
    assert alarms == []
    assert records[0]["source"] == "L1_prefix"


def test_l1_multi_prefix_or_multi_seq_is_shared() -> None:
    # Multi-prefix bar (only seq "1" matches).
    bound, _, _ = bind_scales(
        [make_group(0, ["1"])], [make_scale("1、2.", ["1", "2"])]
    )
    assert bound[0][0].shared is True

    # Multi-seq group (only prefix "1" matches) is shared just the same.
    bound, _, _ = bind_scales(
        [make_group(0, ["1", "2"])], [make_scale("1.", ["1"])]
    )
    assert bound[0][0].shared is True
    assert bound[0][0].source == "L1_prefix"


def test_l2_unique_bar_is_shared_with_every_group() -> None:
    groups = [
        make_group(0, ["1"]),
        make_group(1, ["2"]),
        make_group(2, ["3"]),
    ]
    scales = [make_scale("0—4", [], value=4.0, unit="cm")]

    bound, records, alarms = bind_scales(groups, scales)

    assert [len(items) for items in bound] == [1, 1, 1]
    for items in bound:
        binding = items[0]
        assert binding.scale_id == 0
        assert binding.source == "L2_unique_shared"
        assert binding.shared is True
        assert binding.text == "0—4"
        assert binding.value == 4.0
        assert binding.unit == "cm"
        assert binding.prefix_nos == []
    assert records[0]["source"] == "L2_unique_shared"
    assert records[0]["abandoned"] is False
    assert alarms == []


def test_l2_shared_bar_also_covers_group_without_seq_ids() -> None:
    groups = [make_group(0, []), make_group(1, ["2"])]
    scales = [make_scale("0—4", [])]

    bound, _, alarms = bind_scales(groups, scales)

    assert [len(items) for items in bound] == [1, 1]
    assert [sources(items) for items in bound] == [
        ["L2_unique_shared"], ["L2_unique_shared"],
    ]
    assert alarms == []


def test_scale_records_have_contract_fields_and_normalised_prefixes() -> None:
    groups = [make_group(0, ["1", "2"])]
    scales = [
        make_scale(
            "1、2.",
            ["1", " 1 ", "2", "", " 3 "],
            bbox=(10, 20, 50, 28),
            value=0.5,
            unit="cm",
        ),
        make_scale("9.", ["9"], bbox=(60, 20, 100, 28), value=1.0, unit="m"),
    ]

    bound, records, alarms = bind_scales(groups, scales)

    required = {
        "scale_id", "text", "bbox", "value", "unit",
        "prefix_nos", "abandoned", "source",
    }
    assert len(records) == 2
    assert all(required <= set(record) for record in records)
    assert records[0]["scale_id"] == 0
    assert records[0]["text"] == "1、2."
    assert records[0]["bbox"] == [10, 20, 50, 28]
    assert records[0]["value"] == 0.5
    assert records[0]["unit"] == "cm"
    assert records[0]["prefix_nos"] == ["1", "2", "3"]
    assert records[0]["abandoned"] is False
    assert records[0]["source"] == "L1_prefix"
    assert records[1]["scale_id"] == 1
    assert records[1]["text"] == "9."
    assert records[1]["bbox"] == [60, 20, 100, 28]
    assert records[1]["value"] == 1.0
    assert records[1]["unit"] == "m"
    assert records[1]["prefix_nos"] == ["9"]
    assert records[1]["abandoned"] is False
    assert scale_ids(bound[0]) == [0]
    assert bound[0][0].prefix_nos == ["1", "2", "3"]
    assert bound[0][0].shared is True
    assert alarms == []
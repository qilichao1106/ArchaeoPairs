"""Self-check for T-008: three-tier scale binding + unit application.

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-008/selfcheck_t008.py

All data is synthetic (ViewGroup/ScaleBar/ArtifactMap built in memory; no
image pixels are ever consulted).  UTF-8 log: selfcheck/T-008/selfcheck.log
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from archaeopairs.mapping import (  # noqa: E402
    ArtifactMap, ArtifactUnit, ScaleBinding, ViewGroup,
    apply_scale_bindings, bind_scales,
)
from archaeopairs.models import ScaleBar  # noqa: E402

LOG = Path(__file__).resolve().with_name("selfcheck.log")


def group(group_id, seq_ids):
    return ViewGroup(group_id=group_id, view_ids=[group_id], seq_ids=list(seq_ids))


def scale(text, nos=(), bbox=(0, 0, 10, 4)):
    return ScaleBar(text=text, bbox=bbox, value=None, unit="cm",
                    prefix_nos=list(nos))


def unit(artifact_id, group_ids, status="output"):
    return ArtifactUnit(artifact_id=artifact_id, seq_ids=["1"],
                        view_ids=list(group_ids), group_ids=list(group_ids),
                        status=status)


def amap(units, conflicts=None):
    return ArtifactMap(book_id="synthetic-book", figure_id="fig-synthetic",
                       units=units, conflicts=list(conflicts or []))


def check_l1_prefix():
    groups = [group(0, ["1", "2"]), group(1, ["3", "4", "5", "9"]),
              group(2, ["6", "7", "8"])]
    scales = [scale("1、2.", ["1", "2"]), scale("3～5、9.", ["3", "4", "5", "9"]),
              scale("6～8.", ["6", "7", "8"])]
    bound, records, alarms = bind_scales(groups, scales)
    assert [len(b) for b in bound] == [1, 1, 1]
    assert [b[0].scale_id for b in bound] == [0, 1, 2]
    assert all(b[0].source == "L1_prefix" for b in bound)
    assert all(b[0].shared for b in bound), "multi-prefix / multi-seq -> shared"
    assert bound[1][0].prefix_nos == ["3", "4", "5", "9"]
    assert alarms == [] and all(not r["abandoned"] for r in records)
    assert [r["source"] for r in records] == ["L1_prefix"] * 3


def check_l1_one_scale_many_groups():
    # One bar labelled for all seqs binds every matching group, one copy each.
    groups = [group(0, ["1"]), group(1, ["2"]), group(2, ["3"])]
    bound, records, alarms = bind_scales(groups, [scale("1～3.", ["1", "2", "3"])])
    assert [len(b) for b in bound] == [1, 1, 1]
    assert {b[0].source for b in bound} == {"L1_prefix"}
    assert all(b[0].shared for b in bound)
    # L1 wins over L2: single bar, but it is not shared with the 3rd group.
    bound, _, alarms = bind_scales(groups, [scale("1～2.", ["1", "2"])])
    assert [len(b) for b in bound] == [1, 1, 0]
    assert "E007" in alarms and "group_no_scale:2" in alarms


def check_l2_unique_shared():
    groups = [group(0, ["1"]), group(1, ["2"]), group(2, ["3"])]
    bound, records, alarms = bind_scales(groups, [scale("0 4", [])])
    assert [len(b) for b in bound] == [1, 1, 1]
    for items in bound:
        assert items[0].source == "L2_unique_shared" and items[0].shared is True
        assert items[0].scale_id == 0 and items[0].unit == "cm"
    assert records[0]["source"] == "L2_unique_shared"
    assert alarms == []


def check_l3_multi_no_prefix():
    groups = [group(0, ["1", "2"]), group(1, ["3"]), group(2, ["4"])]
    scales = [scale("1、2.", ["1", "2"]), scale("0 4", []),
              scale("3.", ["3"]), scale("4.", ["4"])]
    bound, records, alarms = bind_scales(groups, scales)
    assert [b[0].scale_id for b in bound] == [0, 2, 3]
    assert records[1]["abandoned"] is True and records[1]["source"] is None
    assert records[0]["abandoned"] is False and records[0]["source"] == "L1_prefix"
    assert alarms.count("E004") == 1 and "E007" not in alarms
    # Never guessed by distance: no group got the abandoned bar.
    assert all(b.scale_id != 1 for items in bound for b in items)
    assert records[1]["text"] == "0 4" and records[1]["bbox"] == [0, 0, 10, 4]


def check_group_no_scale():
    groups = [group(0, ["1"]), group(1, ["2"])]
    bound, _, alarms = bind_scales(groups, [scale("1.", ["1"])])
    assert bound[1] == []
    assert "E007" in alarms and "group_no_scale:1" in alarms
    assert "group_no_scale:0" not in alarms
    # No bars at all -> every group is reported.
    bound, records, alarms = bind_scales(groups, [])
    assert [b for b in bound] == [[], []]
    assert "E007" in alarms
    assert {"group_no_scale:0", "group_no_scale:1"} <= set(alarms)


def check_record_shape():
    bound, records, alarms = bind_scales([group(0, ["1"])],
                                         [scale("1.", ["1"])])
    assert len(records) == 1
    for key in ("scale_id", "text", "bbox", "value", "unit", "prefix_nos",
                "abandoned", "source"):
        assert key in records[0], key
    binding = bound[0][0]
    payload = binding.model_dump()
    assert set(payload) == {"scale_id", "source", "shared", "text", "value",
                            "unit", "prefix_nos"}
    assert payload["scale_id"] == 0 and payload["text"] == "1."
    # ScaleBinding defaults match the frozen contract.
    default = ScaleBinding(scale_id=3)
    assert (default.source, default.shared, default.text) == ("unknown", False, "")
    assert default.value is None and default.unit is None
    assert default.prefix_nos == []


def check_apply_union_and_dedupe():
    groups = [group(0, ["1"]), group(1, ["2"]), group(2, ["3"])]
    scales = [scale("1～3.", ["1", "2", "3"]), scale("2.", ["2"])]
    bound, _, _ = bind_scales(groups, scales)
    # Units spanning groups 0 and 1 collect both bars, once each.
    target = amap([unit("A:1", [0, 1]), unit("A:2", [0, 1, 0])])
    before = target.model_dump()
    out = apply_scale_bindings(target, bound)
    assert out is not target
    assert target.model_dump() == before, "input map must not change"
    for item in out.units:
        assert [b["scale_id"] for b in item.scale_bindings] == [0, 1]
        assert all(b["source"] == "L1_prefix" for b in item.scale_bindings)
        assert item.status == "output"
    # The binding dump is a dict, not a model instance.
    assert isinstance(out.units[0].scale_bindings[0], dict)


def check_apply_no_scale_review():
    groups = [group(0, ["1"]), group(1, ["2"])]
    bound, _, _ = bind_scales(groups, [scale("1.", ["1"])])
    target = amap([unit("A:1", [0]), unit("A:2", [1]), unit("A:3", [2])],
                  conflicts=["keep:me"])
    out = apply_scale_bindings(target, bound)
    statuses = {u.artifact_id: u.status for u in out.units}
    assert statuses == {"A:1": "output", "A:2": "review", "A:3": "review"}
    assert "keep:me" in out.conflicts
    assert out.conflicts.count("group_no_scale:1") == 1
    assert out.conflicts.count("group_no_scale:2") == 1
    assert out.status == "pending_review"
    assert len(out.units) == 3, "bar-less units are kept"
    assert target.units[1].status == "output", "input untouched"


CHECKS = (check_l1_prefix, check_l1_one_scale_many_groups,
          check_l2_unique_shared, check_l3_multi_no_prefix,
          check_group_no_scale, check_record_shape,
          check_apply_union_and_dedupe, check_apply_no_scale_review)


def main() -> int:
    log = open(LOG, "w", encoding="utf-8", newline="\n")
    try:
        for check in CHECKS:
            log.write(f"RUN {check.__name__}\n")
            log.flush()
            check()
        log.write("SELFCHECK OK\n")
    finally:
        log.close()
    print(f"SELFCHECK OK ({len(CHECKS)} checks; log: selfcheck/T-008/selfcheck.log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
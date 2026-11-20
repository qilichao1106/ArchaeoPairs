"""Self-check for T-007: seq binding, view grouping and ArtifactMap assembly.

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-007/selfcheck_t007.py

All data is synthetic (Views/SeqLabels/TextMapping built in memory).  UTF-8
log: selfcheck/T-007/selfcheck.log
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from archaeopairs.mapping import (  # noqa: E402
    ArtifactMap, ArtifactUnit, ViewBinding, ViewGroup, bind_labels_to_views,
    build_artifact_map, group_views, normalize_seq_label,
)
from archaeopairs.models import (  # noqa: E402
    SeqLabel, TextMapping, View,
)

LOG = Path(__file__).resolve().with_name("selfcheck.log")


def view(view_id, bbox, area=None):
    x0, y0, x1, y1 = bbox
    area = (x1 - x0) * (y1 - y0) if area is None else area
    return View(view_id=view_id, bbox=bbox, area=area, mask_rle="", incomplete=False)


def label(text, cx, cy, size=4):
    half = size // 2
    return SeqLabel(text=text, bbox=(cx - half, cy - half, cx + half, cy + half))


def text_mapping(seq_to_artifacts=None, caption=None, case_type="rule_a",
                 conflicts=None):
    return TextMapping(
        seq_to_artifacts=seq_to_artifacts or {},
        caption_artifacts=caption or [],
        case_type=case_type,
        conflicts=conflicts or [],
    )


def build(views, labels, mapping, **kwargs):
    bindings = bind_labels_to_views(views, labels)
    kwargs.setdefault("book_id", "synthetic-book")
    kwargs.setdefault("figure_id", "fig-synthetic")
    return build_artifact_map(views, bindings, mapping, **kwargs)


def check_normalize():
    expected = {"1.": "1", "1、": "1", "1": "1", "①": "1", "⑩": "10",
                "A.": "A", "  2 ": "2", "3．": "3"}
    for text, want in expected.items():
        assert normalize_seq_label(text) == want, text
    for text in ("2、3", "2.、3.", "1～4", "1~4", "1,2", "1，2", "1-4",
                 "", "   ", "图", "序号", None):
        assert normalize_seq_label(text) is None, text


def check_binding_smallest():
    big = view(0, (0, 0, 200, 200))
    small = view(1, (90, 90, 110, 110))
    bindings = bind_labels_to_views([big, small], [label("1.", 100, 100)])
    assert len(bindings) == 1
    assert (bindings[0].view_id, bindings[0].seq_id) == (1, "1")
    assert bindings[0].method == "smallest_containing"
    assert 0.0 < bindings[0].confidence <= 1.0
    # A label touching edges: centre on boundary still counts as inside.
    edge = bind_labels_to_views([big], [label("2", 0, 0)])
    assert edge[0].view_id == 0
    # Centre in no view -> unbound; never distance-guessed.
    out = bind_labels_to_views([big], [label("3", 500, 500)])
    assert out[0].method == "unbound" and out[0].view_id == -1
    assert out[0].seq_id == "3" and out[0].confidence == 0.0


def check_binding_group_label_and_multi():
    v0 = view(0, (10, 10, 100, 100))
    v1 = view(1, (200, 10, 300, 100))
    labels = [label("1、2.", 50, 50), label("2", 250, 50), label("3", 50, 50)]
    bindings = bind_labels_to_views([v0, v1], labels)
    # "1、2." is a group label (skipped); 2 -> v1, 3 -> v0 via containment.
    assert [(b.view_id, b.seq_id) for b in bindings] == [(1, "2"), (0, "3")]
    assert all(b.method == "inside" for b in bindings)


def check_group_same_seq():
    views = [view(0, (0, 0, 10, 10)), view(1, (20, 0, 30, 10)),
             view(2, (40, 0, 50, 10))]
    bindings = [ViewBinding(view_id=0, seq_id="1", method="inside"),
                ViewBinding(view_id=1, seq_id="1", method="inside"),
                ViewBinding(view_id=2, seq_id="2", method="inside")]
    groups, unbound = group_views(views, bindings)
    assert [g.group_id for g in groups] == [0, 1]
    assert groups[0].view_ids == [0, 1] and groups[0].seq_ids == ["1"]
    assert groups[1].view_ids == [2] and groups[1].seq_ids == ["2"]
    assert unbound == []
    assert all(isinstance(g, ViewGroup) for g in groups)
    # Unbound views are reported, never put in a group.
    groups, unbound = group_views(views, bindings[:2])
    assert groups[0].view_ids == [0, 1] and len(groups) == 1
    assert unbound == [{"view_ids": [2], "reason": "no_seq"}]


def check_group_rule_b_all_unlabeled():
    views = [view(i, (i * 20, 0, i * 20 + 10, 10)) for i in range(3)]
    groups, unbound = group_views(views, [], all_unlabeled_rule_b=True)
    assert len(groups) == 1 and groups[0].seq_ids == []
    assert groups[0].view_ids == [0, 1, 2] and unbound == []
    # Without the flag, no labels -> no group, all views unbound.
    groups, unbound = group_views(views, [], all_unlabeled_rule_b=False)
    assert groups == [] and len(unbound) == 3


def check_n_to_one_merge():
    # 4 / 6、7 are one combined drawing split into two views: the two seq
    # groups each declare only M1:29 and merge into one whole-image unit.
    views = [view(0, (0, 0, 10, 10)), view(1, (20, 0, 30, 10))]
    labels = [label("4", 5, 5), label("6", 25, 5), label("7", 25, 6)]
    mapping = text_mapping({"4": ["M1:29"], "6": ["M1:29"], "7": ["M1:29"]},
                           case_type="rule_b")
    amap = build(views, labels, mapping)
    assert isinstance(amap, ArtifactMap)
    assert len(amap.units) == 1
    unit = amap.units[0]
    assert isinstance(unit, ArtifactUnit)
    assert unit.artifact_id == "M1:29"
    assert unit.seq_ids == ["4", "6", "7"]
    assert unit.view_ids == [0, 1]
    assert unit.group_ids == [0, 1, 2]
    assert amap.unbound_seqs == [] and amap.unbound_views == []
    # Labels 4 and 7 both sit on view 0 -> one group with seqs [4, 7]; the
    # lone artifact covers the whole group -> rule B, not whole image.
    narrow = build([view(0, (0, 0, 60, 60)), view(1, (80, 0, 90, 60))],
                   [label("4", 20, 20), label("7", 30, 30)],
                   text_mapping({"4": ["M1:29"], "7": ["M1:29"]},
                                case_type="rule_b"))
    lone = narrow.units[0]
    assert lone.seq_ids == ["4", "7"] and lone.view_ids == [0]
    assert lone.case == "rule_b" and lone.whole_image is False
    assert narrow.unbound_views == [{"view_ids": [1], "reason": "no_seq"}]
    assert unit.case == "rule_b" and unit.whole_image is True
    assert unit.scale_bindings == []
    assert amap.units[0].confidence == 1.0
    assert amap.status == "composed" and amap.case_type == "rule_b"


def check_one_to_n_shared():
    views = [view(0, (0, 0, 100, 100))]
    mapping = text_mapping({"8": ["M139:3", "M139:26"]},
                           case_type="split_same_seq")
    amap = build(views, [label("8.", 50, 50)], mapping)
    assert len(amap.units) == 2
    assert [u.artifact_id for u in amap.units] == ["M139:3", "M139:26"]
    for unit in amap.units:
        assert unit.view_ids == [0] and unit.seq_ids == ["8"]
        assert unit.group_ids == [0] and unit.case == "split_same_seq"
        assert unit.evidence.get("shared_group") is True
    assert amap.status == "composed"


def check_n_to_n_zip():
    views = [view(0, (0, 0, 10, 10)), view(1, (20, 0, 30, 10))]
    mapping = text_mapping({"1": ["M4:2"], "2": ["M4:1"]}, case_type="rule_a")
    amap = build(views, [label("1.", 5, 5), label("2.", 25, 5)], mapping)
    by_art = {u.artifact_id: u for u in amap.units}
    assert set(by_art) == {"M4:2", "M4:1"}
    assert by_art["M4:2"].view_ids == [0] and by_art["M4:2"].seq_ids == ["1"]
    assert by_art["M4:1"].view_ids == [1] and by_art["M4:1"].seq_ids == ["2"]
    assert all(u.case is None for u in amap.units)


def check_rule_b_caption_unique():
    views = [view(0, (0, 0, 50, 50)), view(1, (60, 0, 110, 50))]
    mapping = text_mapping(caption=["M7:1"], case_type="seq_missing")
    amap = build(views, [], mapping, all_unlabeled_rule_b=True)
    assert len(amap.units) == 1 and len(amap.unbound_views) == 0
    unit = amap.units[0]
    assert unit.artifact_id == "M7:1" and unit.source == "caption"
    assert unit.seq_ids == [] and unit.view_ids == [0, 1]
    assert unit.whole_image is True and unit.case == "rule_b"
    assert unit.confidence < 1.0
    # Multiple caption artifacts -> conflict, no unit, no unbound group dup.
    multi = build(views, [], text_mapping(caption=["M7:1", "M7:2"],
                                          case_type="seq_missing"),
                  all_unlabeled_rule_b=True)
    assert multi.units == [] and any("caption" in c for c in multi.conflicts)
    assert multi.status == "pending_review"


def check_unbound_views_and_seqs():
    views = [view(0, (0, 0, 10, 10)), view(1, (20, 0, 30, 10)),
             view(2, (40, 0, 50, 10))]
    # 1 lands in v0, 2 in v1, 9 lands in no view (would be E001), v2 unused.
    labels = [label("1", 5, 5), label("2", 25, 5), label("9", 500, 500)]
    mapping = text_mapping({"1": ["A:1"], "2": ["A:2"], "3": ["A:3"]})
    amap = build(views, labels, mapping)
    assert {u.artifact_id for u in amap.units} == {"A:1", "A:2"}
    assert amap.unbound_views == [{"view_ids": [2], "reason": "no_seq"}]
    assert {s["seq_id"] for s in amap.unbound_seqs} == {"3", "9"}
    assert amap.unbound_seqs[0]["reason"] == "no_view"
    for item in amap.unbound_seqs:
        assert "reason" in item


def check_unmapped_group_vs_unbound_seq():
    views = [view(0, (0, 0, 10, 10))]
    mapping = text_mapping({"1": []})  # seq 1 declared but no artifact
    amap = build(views, [label("1", 5, 5)], mapping)
    assert amap.units == []
    assert amap.unbound_groups and amap.unbound_groups[0]["group_id"] == 0
    assert amap.unbound_groups[0]["reason"] == "unmapped_seq"
    assert amap.unbound_seqs == []
    assert amap.status == "pending_review"


def check_cross_group_merge():
    # Two groups each declare only M5:1 -> single merged unit.
    views = [view(0, (0, 0, 10, 10)), view(1, (20, 0, 30, 10))]
    mapping = text_mapping({"1": ["M5:1"], "2": ["M5:1"]}, case_type="rule_b")
    amap = build(views, [label("1", 5, 5), label("2", 25, 5)], mapping)
    assert len(amap.units) == 1
    unit = amap.units[0]
    assert unit.seq_ids == ["1", "2"] and unit.view_ids == [0, 1]
    assert unit.group_ids == [0, 1] and amap.conflicts == []


def check_cross_group_conflict():
    # M5:1 is alone in its group but group 1 also declares M5:2 -> conflict.
    views = [view(0, (0, 0, 10, 10)), view(1, (20, 0, 30, 10))]
    mapping = text_mapping({"1": ["M5:1"], "2": ["M5:1", "M5:2"]})
    amap = build(views, [label("1", 5, 5), label("2", 25, 5)], mapping)
    assert amap.conflicts.count("cross_group_artifact:M5:1") == 1
    kept = [u for u in amap.units if u.artifact_id == "M5:1"]
    assert len(kept) == 2, "unmerged units kept, no guessing"
    assert {tuple(u.group_ids) for u in kept} == {(0,), (1,)}
    assert amap.status == "pending_review"


def check_text_mapping_conflicts_and_status():
    views = [view(0, (0, 0, 10, 10))]
    mapping = text_mapping({"1": ["A:1"]}, conflicts=["artifact_claimed:x"])
    amap = build(views, [label("1", 5, 5)], mapping)
    assert amap.conflicts == ["artifact_claimed:x"]
    assert amap.status == "pending_review"
    # No views at all -> nothing composed.
    empty = build([], [], text_mapping({}))
    assert empty.units == [] and empty.status == "pending_review"


def check_artifact_map_fields():
    amap = build([view(0, (0, 0, 10, 10))], [label("1", 5, 5)],
                 text_mapping({"1": ["A:1"]}, case_type="rule_a"),
                 line="single_line")
    assert amap.book_id == "synthetic-book" and amap.figure_id == "fig-synthetic"
    assert amap.line == "single_line" and amap.case_type == "rule_a"
    assert amap.alarms == [] and amap.unbound_seqs == []
    payload = amap.model_dump()
    for key in ("book_id", "figure_id", "line", "units", "unbound_groups",
                "unbound_views", "unbound_seqs", "conflicts", "alarms",
                "status"):
        assert key in payload
    assert payload["units"][0]["scale_bindings"] == []
    assert payload["units"][0]["line"] == "single_line"
    # Independent mutable defaults across instances.
    a, b = ArtifactUnit(artifact_id="a"), ArtifactUnit(artifact_id="b")
    a.view_ids.append(0)
    assert b.view_ids == []


CHECKS = (check_normalize, check_binding_smallest,
          check_binding_group_label_and_multi, check_group_same_seq,
          check_group_rule_b_all_unlabeled, check_n_to_one_merge,
          check_one_to_n_shared, check_n_to_n_zip, check_rule_b_caption_unique,
          check_unbound_views_and_seqs, check_unmapped_group_vs_unbound_seq,
          check_cross_group_merge, check_cross_group_conflict,
          check_text_mapping_conflicts_and_status, check_artifact_map_fields)


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
    print(f"SELFCHECK OK ({len(CHECKS)} checks; log: selfcheck/T-007/selfcheck.log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""S8 匹配组装器单元测试（§4.8，拆 Pair+命名规范+去重）。"""
from __future__ import annotations

from archaeopairs.agents import s8

CAP = "图一 出土器物"

def _mask(seq, art=None):
    return {"mask_rle": f"r{seq}", "bbox": (0, 0, 1, 1), "area": 1, "seq": seq, "artifact_id": art}

def _base(case, fused, masks):
    return {"book_id": "b", "figure_id": "fig_1", "fileref": "media/image1.jpg", "caption": CAP,
            "case_type": case, "fused": fused, "masks": masks, "text_artifacts": [],
            "trace_id": "t"}

def test_rule_a_two_pairs(services):
    st = _base("rule_a", {"seq_to_artifacts": {"1": ["M4:1"], "2": ["M4:2"]}},
               [_mask("1"), _mask("2")])
    out = s8.run(st, services)
    arts = {r["artifact_id"] for r in out["pair_records"]}
    assert arts == {"M4:1", "M4:2"}
    for r in out["pair_records"]:
        assert ":" not in r["image_path"] and r["image_path"].endswith(".png")
        assert r["image_path"].startswith("图一_")  # 图号提取

def test_rule_b_single_merged(services):
    st = _base("rule_b", {"seq_to_artifacts": {"1": ["M4:2"], "2": ["M4:2"]}},
               [_mask("1"), _mask("2")])
    out = s8.run(st, services)
    assert len(out["pair_records"]) == 1
    assert out["pair_records"][0]["provenance"]["views"] == 2

def test_split_same_seq_two_pairs(services):
    # 同号多器：一个 seq 两个 artifact → 两个 Pair（不丢数据）
    st = _base("split_same_seq", {"seq_to_artifacts": {"2": ["H1:6", "H1:3"]}}, [_mask("2")])
    out = s8.run(st, services)
    arts = {r["artifact_id"] for r in out["pair_records"]}
    assert arts == {"H1:6", "H1:3"}

def test_dedup_appends_suffix(services):
    # 同名图号去重 _N
    st = _base("rule_a", {"seq_to_artifacts": {"1": ["M4:1"], "2": ["M4:1"]}},
               [_mask("1"), _mask("2")])
    out = s8.run(st, services)
    names = [r["image_path"] for r in out["pair_records"]]
    assert len(names) == len(set(names))

def test_unmapped_mask_pending_not_silent(services):
    st = _base("rule_a", {"seq_to_artifacts": {"1": ["M4:1"]}},
               [_mask("1"), _mask("9")])
    out = s8.run(st, services)
    assert out["status"] == "PENDING_REVIEW"
    assert out["alarms"] == ["E002"]
    assert out["pair_records"] == []


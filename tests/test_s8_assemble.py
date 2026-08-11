"""S8 匹配组装器单元测试（§4.8，确定性）。"""
from __future__ import annotations

from archaeopairs.agents import s8


def _mask(seq, art=None):
    return {"mask_rle": f"r{seq}", "bbox": (0, 0, 1, 1), "area": 1, "seq": seq, "artifact_id": art}


def test_rule_a_two_pairs(services):
    st = {"book_id": "b", "fileref": "media/image1.jpg", "case_type": "rule_a",
          "fused": {"seq_to_artifact": {"1": "M4:1", "2": "M4:2"}},
          "masks": [_mask("1"), _mask("2")], "text_artifacts": []}
    out = s8.run(st, services)
    assert out["assembled"] is True
    arts = {r["artifact_id"] for r in out["pair_records"]}
    assert arts == {"M4:1", "M4:2"}
    assert all(r["image_path"].endswith(".png") for r in out["pair_records"])


def test_rule_b_single_merged(services):
    st = {"book_id": "b", "fileref": "media/image1.jpg", "case_type": "rule_b",
          "fused": {"seq_to_artifact": {"1": "M4:2", "2": "M4:2"}},
          "masks": [_mask("1"), _mask("2")], "text_artifacts": []}
    out = s8.run(st, services)
    assert len(out["pair_records"]) == 1  # 多视图合并为一张
    assert out["pair_records"][0]["provenance"]["views"] == 2


def test_colon_normalized_in_path(services):
    st = {"book_id": "b", "fileref": "m/i.jpg", "case_type": "rule_a",
          "fused": {"seq_to_artifact": {"1": "M4:1"}}, "masks": [_mask("1")], "text_artifacts": []}
    out = s8.run(st, services)
    assert ":" not in out["pair_records"][0]["image_path"]  # 冒号→连字符

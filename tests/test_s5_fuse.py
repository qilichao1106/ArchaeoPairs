"""S5 融合仲裁器单元测试（§4.5，确定性）。"""
from __future__ import annotations

from archaeopairs.agents import s5


def _ni(seq, seq_list, arts):
    return {"seq": seq, "seq_list": seq_list, "name": None, "artifact_ids": arts}


def test_rule_a(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"]), _ni("2", [2], ["M4:2"])],
          "seq_annotations": [1], "text_artifacts": [1]}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_a"
    assert out["fused"]["seq_to_artifact"] == {"1": "M4:1", "2": "M4:2"}
    assert out["confidence"] == 0.95  # 三链


def test_rule_b(services):
    st = {"note_items": [_ni("1", [1], ["M4:2"]), _ni("2", [2], ["M4:2"])],
          "seq_annotations": [], "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_b"
    assert out["confidence"] == 0.5  # 仅链①


def test_split_same_seq(services):
    st = {"note_items": [_ni("2", [2], ["H1:6", "H1:3"])], "seq_annotations": [1], "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "split_same_seq"


def test_range_split(services):
    st = {"note_items": [_ni("1~4", [1, 2, 3, 4], ["M3:4", "M3:2", "M3:3", "M3:1"])],
          "seq_annotations": [1], "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "range_split"
    assert out["fused"]["seq_to_artifact"]["3"] == "M3:3"


def test_seq_missing(services):
    out = s5.run({"note_items": [], "seq_annotations": [], "text_artifacts": []}, services)
    assert out["case_type"] == "seq_missing"

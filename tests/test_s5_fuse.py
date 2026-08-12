"""S5 融合仲裁器单元测试（§4.5，多值映射+冲突+降级+报警）。"""
from __future__ import annotations

from archaeopairs.agents import s5


def _ni(seq, seq_list, arts):
    return {"seq": seq, "seq_list": seq_list, "name": None, "artifact_ids": arts}


def _sa(*seqs):
    return [{"text": str(s), "bbox": (0, 0, 1, 1)} for s in seqs]


def test_rule_a(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"]), _ni("2", [2], ["M4:2"])],
          "seq_annotations": _sa(1, 2), "text_artifacts": [{"artifact_id": "M4:1"}]}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_a"
    assert out["fused"]["seq_to_artifacts"] == {"1": ["M4:1"], "2": ["M4:2"]}
    assert out["confidence"] == 0.95
    assert out["alarms"] == []


def test_rule_b(services):
    st = {"note_items": [_ni("1", [1], ["M4:2"]), _ni("2", [2], ["M4:2"])],
          "seq_annotations": _sa(1, 2), "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_b"
    assert out["confidence"] == 0.85  # 链①+链


def test_split_same_seq_multi_value(services):
    st = {"note_items": [_ni("2", [2], ["H1:6", "H1:3"])], "seq_annotations": _sa(2),
          "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "split_same_seq"
    assert out["fused"]["seq_to_artifacts"]["2"] == ["H1:6", "H1:3"]  # 不截断


def test_range_split(services):
    st = {"note_items": [_ni("1~4", [1, 2, 3, 4], ["M3:4", "M3:2", "M3:3", "M3:1"])],
          "seq_annotations": _sa(1, 2, 3, 4), "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "range_split"
    assert out["fused"]["seq_to_artifacts"]["3"] == ["M3:3"]


def test_seq_missing_degraded_not_alarm(services):
    # 图注整图缺失但链②+③可用 → 降级而非硬报警
    st = {"note_items": [], "figure_note": None, "seq_annotations": _sa(1),
          "text_artifacts": [{"artifact_id": "M4:1"}]}
    out = s5.run(st, services)
    assert out["case_type"] == "seq_missing"
    assert out["degraded"] is True
    assert out["alarms"] == []


def test_alarm_e001_seq_no_drawing(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"]), _ni("2", [2], ["M4:2"])],
          "figure_note": "1. 陶豆（M4:1） 2. 陶壶（M4:2）",
          "seq_annotations": _sa(1), "text_artifacts": []}
    out = s5.run(st, services)
    assert "E001" in out["alarms"]


def test_conflict_detected(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"])], "figure_note": "1. 陶豆（M4:1）",
          "seq_annotations": _sa(1, 9), "text_artifacts": []}
    out = s5.run(st, services)
    assert "9" in out["fused"]["conflicts"]

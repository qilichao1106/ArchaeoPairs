"""S6 组装器三链仲裁单元测试（§4.6.3，多值映射+冲突+降级+报警）。

V0.5.4：融合仲裁自原 S5 并入 S6（原 test_s5_fuse 迁移至此）。
"""
from __future__ import annotations

from archaeopairs.agents import s6


def _ni(seq, seq_list, arts):
    return {"seq": seq, "seq_list": seq_list, "name": None, "artifact_ids": arts}


def _sa(*seqs):
    return [{"text": str(s), "bbox": (0, 0, 1, 1)} for s in seqs]


def test_rule_a(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"]), _ni("2", [2], ["M4:2"])],
          "seq_annotations": _sa(1, 2), "text_artifacts": [{"artifact_id": "M4:1"}]}
    out = s6.run(st, services)
    assert out["case_type"] == "rule_a"
    assert out["fused"]["seq_to_artifacts"] == {"1": ["M4:1"], "2": ["M4:2"]}
    assert out["confidence"] == 0.95
    assert out["alarms"] == []
    assert out["status"] == "COMPOSED"


def test_rule_b(services):
    st = {"note_items": [_ni("1", [1], ["M4:2"]), _ni("2", [2], ["M4:2"])],
          "seq_annotations": _sa(1, 2), "text_artifacts": []}
    out = s6.run(st, services)
    assert out["case_type"] == "rule_b"
    assert out["confidence"] == 0.85  # 链①+链③


def test_split_same_seq_multi_value(services):
    st = {"note_items": [_ni("2", [2], ["H1:6", "H1:3"])], "seq_annotations": _sa(2),
          "text_artifacts": []}
    out = s6.run(st, services)
    assert out["case_type"] == "split_same_seq"
    assert out["fused"]["seq_to_artifacts"]["2"] == ["H1:6", "H1:3"]  # 不截断


def test_range_split(services):
    st = {"note_items": [_ni("1~4", [1, 2, 3, 4], ["M3:4", "M3:2", "M3:3", "M3:1"])],
          "seq_annotations": _sa(1, 2, 3, 4), "text_artifacts": []}
    out = s6.run(st, services)
    assert out["case_type"] == "range_split"
    assert out["fused"]["seq_to_artifacts"]["3"] == ["M3:3"]


def test_seq_missing_degraded_not_alarm(services):
    # 图注整图缺失但链②+③可用 → 降级而非硬报警（不转复核，继续走 S8）
    st = {"note_items": [], "figure_note": None, "seq_annotations": _sa(1),
          "text_artifacts": [{"artifact_id": "M4:1"}]}
    out = s6.run(st, services)
    assert out["case_type"] == "seq_missing"
    assert out["degraded"] is True
    assert out["alarms"] == []
    assert out["status"] == "COMPOSED"


def test_alarm_e001_seq_no_drawing(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"]), _ni("2", [2], ["M4:2"])],
          "figure_note": "1. 陶豆（M4:1） 2. 陶壶（M4:2）",
          "seq_annotations": _sa(1), "text_artifacts": []}
    out = s6.run(st, services)
    assert "E001" in out["alarms"]
    assert out["status"] == "PENDING_REVIEW"  # 报警即停（V0.5.4：转复核不回环）


def test_conflict_detected(services):
    st = {"note_items": [_ni("1", [1], ["M4:1"])], "figure_note": "1. 陶豆（M4:1）",
          "seq_annotations": _sa(1, 9), "text_artifacts": []}
    out = s6.run(st, services)
    assert "9" in out["fused"]["conflicts"]


def test_e2_binds_unlabeled_atom(services):
    # E2 序号绑定：无号原子按链③序号 bbox 中心落入原子 bbox 绑定
    st = {"note_items": [_ni("1", [1], ["M4:1"])],
          "seq_annotations": [{"text": "1", "bbox": (30, 30, 40, 40)}],
          "text_artifacts": [],
          "atom_masks": [{"mask_rle": "r", "bbox": (10, 10, 100, 100), "area": 100}]}
    out = s6.run(st, services)
    assert out["atom_masks"][0]["seq_id"] == "1"


def test_e2_bind_conflict_recorded(services):
    # 双序号同落一原子 → 冲突登记不猜测（禁猜测）
    st = {"note_items": [_ni("1", [1], ["M4:1"])],
          "seq_annotations": [{"text": "1", "bbox": (30, 30, 40, 40)},
                              {"text": "2", "bbox": (50, 50, 60, 60)}],
          "text_artifacts": [],
          "atom_masks": [{"mask_rle": "r", "bbox": (10, 10, 100, 100), "area": 100}]}
    out = s6.run(st, services)
    assert out["atom_masks"][0].get("seq_id") is None
    assert any(c.startswith("ambiguous_bind") for c in out["fused"]["conflicts"])


def test_serial_anomalies_flow_to_conflicts(services):
    # S5 serial_set 校验异常随仲裁写入 conflicts（§4.5.1 serial_set 校验）
    st = {"note_items": [], "seq_annotations": _sa(1, 1, 5), "text_artifacts": []}
    st["serial_anomalies"] = ["duplicate_serial:1", "non_contiguous_serials:1..5"]
    out = s6.run(st, services)
    assert "serial_check:duplicate_serial:1" in out["fused"]["conflicts"]

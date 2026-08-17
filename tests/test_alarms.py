"""硬约束报警 E001–E007 与比例尺三级归属测试（异常报警字典（§6.3）/ 序号硬匹配与比例尺三级（§5.3））。"""
from __future__ import annotations

from archaeopairs.agents.alarms import assign_scales, detect_alarms


def _sa(*seqs):
    return [{"text": str(s), "bbox": (0, 0, 1, 1)} for s in seqs]


def test_e002_drawing_no_note_declaration():
    st = {"figure_note": "1. 陶豆（M4:1）", "note_items": [
        {"seq": "1", "seq_list": [1], "artifact_ids": ["M4:1"]}],
        "seq_annotations": _sa(1, 3)}
    assert "E002" in detect_alarms(st)


def test_e004_multi_scale_unseqed():
    st = {"scale_annotations": [{"seq_ref": None}, {"seq_ref": None}]}
    assert "E004" in detect_alarms(st)


def test_e005_multi_no_seq_list():
    st = {"figure_note": "陶豆 陶壶", "note_items": [], "seq_annotations": _sa(1, 2),
          "masks": [{"mask_rle": "a"}, {"mask_rle": "b"}]}
    assert "E005" in detect_alarms(st)


def test_e006_incomplete_mask():
    st = {"masks": [{"mask_rle": "a", "incomplete": True}]}
    assert "E006" in detect_alarms(st)


def test_no_alarm_when_consistent():
    st = {"figure_note": "1. 陶豆（M4:1）", "note_items": [
        {"seq": "1", "seq_list": [1], "artifact_ids": ["M4:1"]}],
        "seq_annotations": _sa(1), "scale_annotations": [{"seq_ref": None}]}
    assert detect_alarms(st) == []


def test_scale_level2_single_shared():
    out, alarms = assign_scales([{"seq_ref": None}], ["1", "2"])
    assert out == {"0": "shared"} and alarms == []


def test_scale_level1_hard_match():
    scales = [{"seq_ref": "1"}, {"seq_ref": "2"}]
    out, alarms = assign_scales(scales, ["1", "2"])
    assert out == {"0": "1", "1": "2"} and alarms == []


def test_scale_level3_alarm():
    scales = [{"seq_ref": "1"}, {"seq_ref": None}]
    out, alarms = assign_scales(scales, ["1"])
    assert "E004" in alarms

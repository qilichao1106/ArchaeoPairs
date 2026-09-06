"""硬约束回归测试（硬约束追溯矩阵（§12）逐条断言，违规即失败）。

V0.5.4：掩膜硬约束（禁 bbox / E006）在 S4 视觉分割器；比例尺三级归属与
说明文字并入在 S6 组装器。硬约束不可被 flag 关闭（s9_loop 已随 V0.5.4 移除）。
"""
from __future__ import annotations

import pytest

from archaeopairs.agents import s4, s6, s10
from archaeopairs.errors import HardConstraintError


def test_mask_must_not_be_bbox(services, base_state):
    # 注入无掩膜(RLE)的 bbox 切割结果 → S4 必须抛硬约束异常
    services.sam.segment = lambda **kw: [{"bbox": (0, 0, 1, 1), "area": 1, "seq_id": "1"}]
    with pytest.raises(HardConstraintError):
        s4.run(base_state, services)


def test_mask_incomplete_raises_e006(services, base_state):
    # E006 共享基准线致掩膜残缺 → 报警即停
    services.sam.segment = lambda **kw: [{"mask_rle": "r", "bbox": (0, 0, 1, 1),
                                          "area": 1, "seq_id": "1", "incomplete": True}]
    with pytest.raises(HardConstraintError):
        s4.run(base_state, services)


def test_alarm_seq_missing_goes_pending(services, base_state):
    st = dict(base_state)
    st["case_type"] = "seq_missing"
    out = s10.run(st, services)
    assert out["status"] == "PENDING_REVIEW"


def test_converged_goes_output(services, base_state):
    st = dict(base_state)
    st["case_type"] = "rule_a"
    out = s10.run(st, services)
    assert out["status"] == "OUTPUT"


def test_hard_constraint_not_flag_closable(services, base_state):
    # 硬约束异常不依赖任何 flag（V0.5.4 s9_loop 已移除，硬约束本就不可关）
    services.sam.segment = lambda **kw: [{"bbox": (0, 0, 1, 1)}]
    with pytest.raises(HardConstraintError):
        s4.run(base_state, services)


def test_s6_assign_shared_scale(services, base_state):
    st = dict(base_state)
    st["scale_annotations"] = [{"seq_ref": None}]
    st["trace_id"] = "t-scale"
    out = s6.run(st, services)
    assert all(m["scale_level"] == 2 for m in out["atom_masks"])


def test_s6_scale_level3_goes_pending(services, base_state):
    # 三级报警（无序号比例尺 × 多比例尺）→ E004 → PENDING_REVIEW（报警即停）
    st = dict(base_state)
    st["scale_annotations"] = [{"seq_ref": "1"}, {"seq_ref": None}]
    st["trace_id"] = "t-scale3"
    out = s6.run(st, services)
    assert out["status"] == "PENDING_REVIEW"
    assert "E004" in out["alarms"]


def test_s6_merges_text_and_scale_regions(services, base_state):
    st = dict(base_state)
    st["seq_annotations"] = [{"text": "1", "bbox": (0, 0, 1, 1)}]
    st["scale_annotations"] = [{"text": "0-8cm", "bbox": (0, 1, 1, 1), "seq_ref": "1"}]
    st["atom_masks"] = [{"mask_rle": "r", "bbox": (0, 0, 10, 10), "area": 100}]
    st["trace_id"] = "t-merge"
    out = s6.run(st, services)
    first = out["atom_masks"][0]
    assert first["aux_regions"]["text"]
    assert first["aux_regions"]["scale"]

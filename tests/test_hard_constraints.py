"""硬约束回归测试（§12 追溯矩阵逐条断言，违规即失败）。"""
from __future__ import annotations

import pytest

from archaeopairs.agents import s6, s10
from archaeopairs.errors import HardConstraintError


def test_mask_must_not_be_bbox(services, base_state):
    # 注入无掩膜(RLE)的 bbox 切割结果 → 必须抛硬约束异常
    services.sam.segment = lambda **kw: [{"bbox": (0, 0, 1, 1), "area": 1, "seq": "1"}]
    with pytest.raises(HardConstraintError):
        s6.run(base_state, services)


def test_alarm_seq_missing_goes_pending(services, base_state):
    st = dict(base_state)
    st["case_type"] = "seq_missing"
    st["defect_history"] = []
    out = s10.run(st, services)
    assert out["status"] == "PENDING_REVIEW"


def test_converged_goes_output(services, base_state):
    st = dict(base_state)
    st["case_type"] = "rule_a"
    st["defect_history"] = [0]
    out = s10.run(st, services)
    assert out["status"] == "OUTPUT"


def test_hard_constraint_not_flag_closable(services, base_state):
    # 即使关闭 s9_loop，硬约束异常仍抛出（不可被 flag 关闭）
    services.flags.s9_loop = False
    services.sam.segment = lambda **kw: [{"bbox": (0, 0, 1, 1)}]
    with pytest.raises(HardConstraintError):
        s6.run(base_state, services)

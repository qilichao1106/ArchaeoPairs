"""各 Node 函数：输入 State 键 -> 调用智能体 -> 输出 State 键（§3.4.1 映射）。

统一异常拦截（§3.1/§6.3）：AlarmError/HardConstraintError→PENDING_REVIEW+报警码，
CostCapExceeded→PENDING_REVIEW，保证"报警即停、禁输出 PNG"。
"""
from __future__ import annotations

from typing import Callable

from ..agents import Services, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10
from ..errors import AlarmError, HardConstraintError
from ..gateway import CostCapExceeded

NodeFn = Callable[[dict], dict]


def _guard(fn: NodeFn) -> NodeFn:
    def wrapped(st: dict) -> dict:
        try:
            return fn(st)
        except AlarmError as exc:
            return {"alarms": [exc.code], "status": "PENDING_REVIEW"}
        except HardConstraintError:
            return {"alarms": ["E007"], "status": "PENDING_REVIEW"}
        except CostCapExceeded:
            return {"status": "PENDING_REVIEW", "exclude_reason": "cost_cap"}
    return wrapped


def build_nodes(svc: Services) -> dict[str, NodeFn]:
    """Node 名对齐《编码开发要求》4.1 映射表。"""
    raw = {
        "parse_report": lambda st: s1.run(st, svc),
        "classify_figure": lambda st: s2.run(st, svc),
        "parse_text": lambda st: s3.run(st, svc),
        "parse_image": lambda st: s4.run(st, svc),
        "fuse": lambda st: s5.run(st, svc),
        "segment": lambda st: s6.run(st, svc),
        "parse_plate": lambda st: s7.run(st, svc),
        "assemble": lambda st: s8.run(st, svc),
        "supervise": lambda st: s9.run(st, svc),
        "bridge_review": lambda st: s10.run(st, svc),
    }
    return {name: _guard(fn) for name, fn in raw.items()}

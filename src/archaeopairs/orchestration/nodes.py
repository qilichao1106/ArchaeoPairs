"""各 Node 函数：输入 State 键 -> 调用智能体 -> 输出 State 键（§3.4.1 映射）。"""
from __future__ import annotations

from typing import Callable

from ..agents import Services, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10

NodeFn = Callable[[dict], dict]


def build_nodes(svc: Services) -> dict[str, NodeFn]:
    """Node 名对齐《编码开发要求》4.1 映射表。"""
    return {
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

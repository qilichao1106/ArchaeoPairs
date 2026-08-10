# -*- coding: utf-8 -*-
"""共享 State（黑板）与通信协议（方案 §3.4）。

设计要点：
- Agent 间不直接调用，仅读写 PairState 的 typed 字段；
- 每次跨 Agent 写入由编排层追加 AgentMessage 审计链（trace_id 贯穿）；
- State 可整体 JSON 序列化，供 checkpoint 持久化与 interrupt/resume 恢复。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class AgentMessage:
    trace_id: str
    src: str                 # from（字段名 from 与关键字冲突，落盘时改名）
    dst: str
    type: str                # produce / update / alarm / review
    payload_ref: str         # 产物字段名或文件路径
    schema_version: str = "v1"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["from"] = d.pop("src")
        return d

    @staticmethod
    def from_dict(d: dict) -> "AgentMessage":
        d = dict(d)
        d["src"] = d.pop("from", "")
        return AgentMessage(**d)


@dataclass
class PairState:
    """单 figure 处理的全生命周期状态（字段分组对应方案 §3.4）。"""
    # ---- 标识
    book_id: str = ""
    figure_id: str = ""
    trace_id: str = ""
    rule_version: str = "r1"
    prompt_version: str = "p1"
    # ---- 产物（各 Agent 写入）
    figure_index: dict = field(default_factory=dict)    # A0
    text_note: dict = field(default_factory=dict)       # A1a
    artifact_records: list = field(default_factory=list)  # A1b（报告级，按 figure 过滤使用）
    text_side: dict = field(default_factory=dict)       # A1c
    image_side: dict = field(default_factory=dict)      # A3
    figure_type: str = ""                               # A2: type_a/plate/non
    fused_mapping: dict = field(default_factory=dict)   # A4
    vision_segments: dict = field(default_factory=dict)  # A5
    plate_segments: dict = field(default_factory=dict)  # A6
    pairs: list = field(default_factory=list)           # A7
    # ---- 运行态
    agent_states: dict = field(default_factory=dict)    # agent -> idle/running/failed/...
    errors: list = field(default_factory=list)          # [{code,agent,message}]
    confidence: float = 0.0
    review_flag: bool = False
    need_rerun: list = field(default_factory=list)
    current_node: str = ""                              # 编排层恢复锚点
    # ---- 审计链
    messages: list = field(default_factory=list)        # [AgentMessage.to_dict()]

    @property
    def idem_key(self) -> str:
        return f"{self.book_id}:{self.figure_id}:{self.rule_version}:{self.prompt_version}"

    def record(self, msg: AgentMessage) -> None:
        self.messages.append(msg.to_dict())

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PairState":
        return PairState(**{k: v for k, v in d.items() if k in PairState.__dataclass_fields__})

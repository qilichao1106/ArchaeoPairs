# -*- coding: utf-8 -*-
"""Agent 统一接口契约（方案 §4 AgentInterface）。

所有 Agent 继承 AgentInterface，实现 run(state, ctx)：
- 读取 state 中上游产物字段，写入本 Agent 产物字段；
- 不确定场景抛 ReviewRequired（编排层转 interrupt），致命错误抛 AgentError(fatal=True)；
- 与编排框架解耦：Agent 不感知 LangGraph/AgentScope，仅依赖本接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from .state import PairState, AgentMessage


class AgentContext(Protocol):
    """编排层注入的运行时上下文（模型网关/配置/日志）。"""
    gateway: Any             # ModelGateway
    config: dict             # flags 三层配置展开
    book_dir: str            # data/<book_id>/ 产物根目录


class AgentInterface(ABC):
    name: str = ""
    timeout_s: int = 10
    prompt_deps: list[str] = []
    input_fields: list[str] = []     # 声明式输入（文档化+调试用）
    output_fields: list[str] = []

    @abstractmethod
    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        """执行并返回更新后的 state（原地修改亦可）。"""
        ...

    def health_check(self) -> bool:
        return True

    def emit(self, state: PairState, dst: str, payload_ref: str,
             mtype: str = "produce") -> None:
        """跨 Agent 写入时追加审计链（§3.4 通信协议）。"""
        state.record(AgentMessage(trace_id=state.trace_id, src=self.name,
                                  dst=dst, type=mtype, payload_ref=payload_ref))

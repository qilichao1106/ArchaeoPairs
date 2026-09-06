"""LangGraph StateGraph 组装层（LangGraph 编排落地（§3.4）/ 智能体职责定义（§4））。编排层只做流程控制，不写业务。"""
from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from ..agents import Services
from ..state import GraphState
from . import nodes, routing


def build_graph(svc: Services, checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(GraphState)
    fns = nodes.build_nodes(svc)
    for name, fn in fns.items():
        g.add_node(name, fn)  # type: ignore[call-overload]

    g.add_edge(START, "s1_index")
    g.add_conditional_edges("s1_index", routing.route_s1,
                            {"s2_classify": "s2_classify", END: END})
    g.add_conditional_edges("s2_classify", routing.route_classify,
                            ["s3_text", "s7_single", END])
    # V0.5.4 串行拓扑（§3.4.5）：多器物线图 S3 文本解析先行供链①②，
    # S4 分割 → S5 识别 → S6 组装串行（与 extract 原型 seg→rec→bind 一致）。
    g.add_edge("s3_text", "s4_segment")
    g.add_edge("s4_segment", "s5_recognize")
    g.add_edge("s5_recognize", "s6_compose")
    g.add_conditional_edges("s6_compose", routing.route_compose,
                            {"s8_assemble": "s8_assemble", "s10_review": "s10_review"})
    # V0.5.1 single path: S7 -> S8 -> S10（整图即 Pair，不经 S9）
    g.add_conditional_edges("s7_single", routing.route_single,
                            {"s8_assemble": "s8_assemble", "s10_review": "s10_review", END: END})
    g.add_conditional_edges("s8_assemble", routing.route_assemble,
                            {"s9_supervise": "s9_supervise", "s10_review": "s10_review"})
    # S9 纯质检门（V0.5.4）：pass/reject 均进 S10 两级分流（输出入库 / 转复核），
    # 无自动修正回环（route_supervise 回环边删除）。
    g.add_conditional_edges("s9_supervise", routing.route_qc, {"s10_review": "s10_review"})
    g.add_edge("s10_review", END)

    return g.compile(checkpointer=checkpointer)

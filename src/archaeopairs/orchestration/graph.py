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

    g.add_edge(START, "parse_report")
    g.add_conditional_edges("parse_report", routing.route_s1,
                            {"classify_figure": "classify_figure", END: END})
    g.add_conditional_edges("classify_figure", routing.route_classify,
                            ["parse_text", "parse_image", "parse_single", END])
    g.add_edge("parse_text", "fuse")
    g.add_edge("parse_image", "fuse")
    # V0.5.1 single path: S7 -> S8 -> S10（整图即 Pair，不经 S9）
    g.add_conditional_edges("parse_single", routing.route_single,
                            {"assemble": "assemble", "bridge_review": "bridge_review", END: END})
    g.add_conditional_edges("fuse", routing.route_fuse,
                            {"segment": "segment", "bridge_review": "bridge_review"})
    # V0.5.1 拓扑（§3.4.5）：单器物 S1-S2-S7-S8-S10（整图即 Pair，不经 S9）；
    # 多器物线图 S1-S2-S3/S4-S5-S6-S8-S9-S10（S6→S8 先组装，S8→S9 监督终检，S10 两级）。
    g.add_edge("segment", "assemble")  # S6 -> S8
    g.add_conditional_edges("assemble", routing.route_assemble,
                            {"supervise": "supervise", "bridge_review": "bridge_review"})

    def _route_sup(st: dict):
        return routing.route_supervise(st, svc.thresholds.max_iteration, svc.flags.s9_loop)

    g.add_conditional_edges("supervise", _route_sup,
                            {"segment": "segment", "parse_image": "parse_image",
                             "parse_text": "parse_text", "assemble": "assemble",
                             "bridge_review": "bridge_review"})
    g.add_edge("bridge_review", END)

    return g.compile(checkpointer=checkpointer)

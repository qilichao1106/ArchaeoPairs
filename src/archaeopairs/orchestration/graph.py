"""LangGraph StateGraph 组装层（§3.4 / 4.x）。编排层只做流程控制，不写业务。"""
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
                            ["parse_text", "parse_image", "parse_plate", END])
    g.add_edge("parse_text", "fuse")
    g.add_edge("parse_image", "fuse")
    # 彩板路径经 S9 必选终检（V0.2 §4.7.3）：ASM_VALIDATED→supervise→bridge_review
    g.add_conditional_edges("parse_plate", routing.route_plate,
                            {"supervise": "supervise", "bridge_review": "bridge_review", END: END})
    g.add_conditional_edges("fuse", routing.route_fuse,
                            {"segment": "segment", "bridge_review": "bridge_review"})
    g.add_edge("segment", "supervise")
    g.add_edge("assemble", "supervise")

    def _route_sup(st: dict):
        return routing.route_supervise(st, svc.thresholds.max_iteration, svc.flags.s9_loop)

    g.add_conditional_edges("supervise", _route_sup,
                            {"segment": "segment", "parse_image": "parse_image",
                             "parse_text": "parse_text", "assemble": "assemble",
                             "bridge_review": "bridge_review"})
    g.add_edge("bridge_review", END)

    return g.compile(checkpointer=checkpointer)

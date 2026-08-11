"""LangGraph 拓扑 / 端到端 / checkpointer 测试（§3.4 / 7.2）。"""
from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from archaeopairs.orchestration import build_graph

NODES = {"parse_report", "classify_figure", "parse_text", "parse_image", "fuse",
         "segment", "parse_plate", "assemble", "supervise", "bridge_review"}


def test_topology_has_10_nodes(services):
    app = build_graph(svc=services)
    names = set(app.get_graph().nodes)
    assert NODES.issubset(names)


def test_end_to_end_output(services, base_state, tmp_path: Path):
    db = tmp_path / "ckpt.sqlite3"
    with SqliteSaver.from_conn_string(str(db)) as ckpt:
        app = build_graph(services, checkpointer=ckpt)
        cfg = {"configurable": {"thread_id": "t:e2e"}}
        result = app.invoke(base_state, config=cfg)
    assert result["status"] == "OUTPUT"
    assert len(result["pair_records"]) == 2  # rule_a 两器物
    arts = {r["artifact_id"] for r in result["pair_records"]}
    assert arts == {"M4:1", "M4:2"}


def test_checkpointer_persists(services, base_state, tmp_path: Path):
    db = tmp_path / "ckpt2.sqlite3"
    thread = "t:resume"
    with SqliteSaver.from_conn_string(str(db)) as ckpt:
        app = build_graph(services, checkpointer=ckpt)
        app.invoke(base_state, config={"configurable": {"thread_id": thread}})
    with SqliteSaver.from_conn_string(str(db)) as ckpt2:
        app2 = build_graph(services, checkpointer=ckpt2)
        st = app2.get_state({"configurable": {"thread_id": thread}})
        assert st is not None and st.values.get("status") == "OUTPUT"

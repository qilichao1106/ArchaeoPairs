"""复核闭环与报警路由测试（调度复核桥接器（§4.10）/ 异常报警字典（§6.3））：报警即 PENDING_REVIEW、禁输出。"""
from __future__ import annotations

from langgraph.checkpoint.sqlite import SqliteSaver

from archaeopairs.agents import Services
from archaeopairs.capability import MockOCR, MockSAM, MockVLM
from archaeopairs.capability.compose import MockCompositor
from archaeopairs.config import load_flags, load_thresholds
from archaeopairs.gateway import Gateway
from archaeopairs.integrations import MockReviewBridge
from archaeopairs.orchestration import build_graph
from archaeopairs.storage import LocalObjectStore


def _services(ground, tmp_path, require_human=False):
    th = load_thresholds()
    fl = load_flags()
    fl.require_human = require_human
    store = LocalObjectStore(tmp_path / "obj")
    return Services(vlm=MockVLM(ground), sam=MockSAM(ground), ocr=MockOCR(ground),
                    gateway=Gateway(),
                    thresholds=th, flags=fl, object_store=store,
                    compositor=MockCompositor(store), review_bridge=MockReviewBridge(),
                    ground=ground)


def test_e006_alarm_routes_to_review_no_output(base_state, synth_book, tmp_path):
    _, ground, _ = synth_book
    ground[base_state["figure_id"]]["inject_incomplete"] = True
    svc = _services(ground, tmp_path)
    with SqliteSaver.from_conn_string(str(tmp_path / "c.sqlite3")) as ckpt:
        app = build_graph(svc, checkpointer=ckpt)
        res = app.invoke(base_state, config={"configurable": {"thread_id": "t:e006"}})
    assert res["status"] == "PENDING_REVIEW"
    assert res.get("alarms") == ["E006"]
    assert not res.get("pair_records")  # 禁输出


def test_s10_creates_review_task_idempotent(base_state, synth_book, tmp_path):
    _, ground, _ = synth_book
    svc = _services(ground, tmp_path)
    st = dict(base_state)
    st["alarms"] = ["E001"]
    out = __import__("archaeopairs.agents.s10", fromlist=["s10"]).run(st, svc)
    assert out["status"] == "PENDING_REVIEW"
    ev = out["review_events"][0]["event_id"]
    assert svc.review_bridge.callback(event_id=ev, result={}) is True
    assert svc.review_bridge.callback(event_id=ev, result={}) is False  # 幂等去重


def test_s10_no_improve_pending(base_state, synth_book, tmp_path):
    _, ground, _ = synth_book
    svc = _services(ground, tmp_path)
    st = dict(base_state)
    st["no_improve"] = True
    st["defect_history"] = [3, 3]
    out = __import__("archaeopairs.agents.s10", fromlist=["s10"]).run(st, svc)
    assert out["status"] == "PENDING_REVIEW"

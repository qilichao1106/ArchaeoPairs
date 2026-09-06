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


def test_s9_qc_reject_goes_pending(base_state, synth_book, tmp_path):
    # S9 纯质检（V0.5.4）：注入缺陷 → qc_verdict=reject → S10 转 PENDING_REVIEW
    from archaeopairs.agents import s9, s10
    _, ground, _ = synth_book
    ground[base_state["figure_id"]]["inject_defects"] = [
        {"type": "under_seg", "location": "mask#1", "severity": "high"}]
    svc = _services(ground, tmp_path)
    st = dict(base_state)
    st["assembled"] = True
    out = s9.run(st, svc)
    assert out["qc_report"]["qc_verdict"] == "reject"
    assert out["qc_report"]["evidence"]["defects"]
    st2 = dict(st)
    st2["qc_report"] = out["qc_report"]
    out2 = s10.run(st2, svc)
    assert out2["status"] == "PENDING_REVIEW"


def test_s9_qc_pass_goes_output(base_state, synth_book, tmp_path):
    # 质检合格（defect_list 为空）→ 经 S10 输出入库
    from archaeopairs.agents import s9, s10
    _, ground, _ = synth_book
    svc = _services(ground, tmp_path)
    st = dict(base_state)
    st["assembled"] = True
    out = s9.run(st, svc)
    assert out["qc_report"]["qc_verdict"] == "pass"
    st2 = dict(st)
    st2["qc_report"] = out["qc_report"]
    st2["case_type"] = "rule_a"
    out2 = s10.run(st2, svc)
    assert out2["status"] == "OUTPUT"

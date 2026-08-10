# -*- coding: utf-8 -*-
"""A1a 图注解析 / A4 融合仲裁 / 编排中断恢复 单元测试。

运行：python -m pytest tests/test_pipeline.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from archaeopairs.agents import AGENTS
from archaeopairs.gateway import MockGateway
from archaeopairs.orchestration.graph import Checkpointer, GraphRunner
from archaeopairs.state import PairState


class Ctx:
    def __init__(self, gateway=None, config=None, book_dir=""):
        self.gateway = gateway or MockGateway()
        self.config = config or {}
        self.book_dir = book_dir


def _state_with_note(note: str) -> PairState:
    s = PairState(book_id="t", figure_id="fig-0001",
                  trace_id="t:fig-0001:r1:p1")
    s.figure_index = {"figure_id": "fig-0001", "fileref": "media/x.jpg",
                      "figure_no": {"norm": "图16", "original": "图一六"},
                      "caption": "图一六 出土遗物", "note_text": note,
                      "case_pred": "case2", "caption_mode": "artifact"}
    return s


def test_a1a_direct_mapping():
    s = AGENTS["A1a"].run(_state_with_note("1.瓷碗(M4:2) 2.陶罐(M4:3)"), Ctx())
    assert s.text_note["seq_to_id"] == {"1": ["M4-2"], "2": ["M4-3"]}
    assert s.text_note["confidence"] == 0.95
    assert s.messages and s.messages[0]["from"] == "A1a"


def test_a1a_residual_degraded_with_mock():
    # Mock 网关对 A1a LLM 二次解析不可用 → degraded
    s = AGENTS["A1a"].run(_state_with_note("1.瓷碗(M4:2)；残件若干"), Ctx())
    assert s.text_note["degraded"] is True
    assert s.text_note["seq_to_id"] == {"1": ["M4-2"]}


def test_a4_full_agree():
    s = _state_with_note("")
    s.text_side = {"seq_to_id": {"1": ["M4-2"]}, "id_to_desc": {"M4-2": "瓷碗…"},
                   "note_provenance": "both", "confidence": 0.95}
    s.image_side = {"complete": True, "seq_set": ["1"],
                    "seq_to_id": {"1": ["M4-2"]}, "scales": [], "orientation": "h"}
    s = AGENTS["A4"].run(s, Ctx())
    fm = s.fused_mapping
    assert fm["seq_to_id"] == {"1": ["M4-2"]}
    assert fm["per_elem_provenance"]["1"]["confidence"] == 0.95
    assert fm["review_flag"] is False
    assert fm["case_type"] == "rule_a"


def test_a4_rule_b_multi_view():
    s = _state_with_note("")
    s.text_side = {"seq_to_id": {"1": ["M4-2"], "2": ["M4-2"]},
                   "id_to_desc": {"M4-2": "铜舟…"}, "note_provenance": "both"}
    s.image_side = {"complete": False, "seq_set": [], "seq_to_id": {}, "scales": []}
    s = AGENTS["A4"].run(s, Ctx())
    assert s.fused_mapping["case_type"] == "rule_b"
    assert s.fused_mapping["id_to_seqs"] == {"M4-2": ["1", "2"]}


def test_a4_conflict_unresolvable_review():
    s = _state_with_note("")
    s.text_side = {"seq_to_id": {"1": ["M4-2"]}, "id_to_desc": {}, "confidence": 0.95}
    s.image_side = {"complete": True, "seq_set": ["1"],
                    "seq_to_id": {"1": ["M4-9"]}, "scales": [], "orientation": "h"}
    s = AGENTS["A4"].run(s, Ctx())   # Mock A4 仲裁返回空 → unresolvable
    assert s.fused_mapping["per_elem_provenance"]["1"]["source"] == "unresolvable"
    assert s.fused_mapping["review_flag"] is True


def test_a4_text_only_single_source():
    s = _state_with_note("")
    s.text_side = {"seq_to_id": {"1": ["M4-2"]}, "id_to_desc": {},
                   "note_provenance": "note_only"}
    s.image_side = {"complete": False, "seq_set": [], "seq_to_id": {}, "scales": []}
    s = AGENTS["A4"].run(s, Ctx())
    p = s.fused_mapping["per_elem_provenance"]["1"]
    assert p["source"] == "note_only" and p["confidence"] == 0.7


def test_graph_interrupt_and_resume(tmp_path):
    """A5 因 OCR 缺失 fail-closed → blocked_review；resume 自 A4 重放。"""
    runner = GraphRunner(AGENTS, Checkpointer(str(tmp_path / "cp.db")))
    s = _state_with_note("1.瓷碗(M4:2)")
    ctx = Ctx(config={"__figure__": type("F", (), {
        "figure_id": "fig-0001", "fileref": "media/x.jpg", "caption": "图一六 出土遗物",
        "figure_no_norm": "图16", "figure_no_original": "图一六",
        "note_text": "1.瓷碗(M4:2)", "caption_mode": "artifact",
        "case_pred": "case2", "media_exists": True, "page": "1"})(),
        "__artifact_records__": [{
            "artifact_id": "M4-2", "original_id": "M4:2", "name": "瓷碗",
            "description": "瓷碗，敞口。", "figure_refs": [("图16", 1)],
            "plate_refs": [], "page": "1", "ref_seqs": [1]}]})
    r = runner.run(s, ctx)
    assert r.status == "blocked_review"
    assert r.review["resume_node"] == "A5"       # OCR 缺失在 A5 触发

    # resume：人工确认后自 A4 重放（映射类决策）
    r2 = runner.resume(s.trace_id, ctx, {"kind": "mapping", "patch": {}})
    assert r2.figure_id == "fig-0001"

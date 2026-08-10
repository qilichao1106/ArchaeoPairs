# -*- coding: utf-8 -*-
"""A1a 图注解析（链①·figure-note 强源）：四形态 → seq→ids 直接映射。

决策树（方案 §4-A1a）：残差=0→conf 0.95；残差>0→LLM 二次→0.8；仍残差→degraded。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..regexes import parse_figure_note
from ..state import PairState


class A1aNoteParse(AgentInterface):
    name = "A1a"
    timeout_s = 10
    prompt_deps = ["P-A1a"]
    input_fields = ["figure_index"]
    output_fields = ["text_note"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        note_text = state.figure_index.get("note_text", "")
        parsed = parse_figure_note(note_text)

        seq_to_id: dict[str, list[str]] = {}
        for e in parsed.entries:
            if e.form == "range" and e.ids and len(e.ids) == len(e.seqs):
                for s, i in zip(e.seqs, e.ids):       # 范围式按位置序展开
                    seq_to_id[s] = [i]
            elif e.form == "same_id":
                if len(e.ids) == len(e.seqs):          # 一一对应
                    for s, i in zip(e.seqs, e.ids):
                        seq_to_id[s] = [i]
                else:                                   # 共享 ids（同号拆 Pair 共享子图）
                    for s in e.seqs:
                        seq_to_id[s] = list(e.ids)
            else:
                for s in e.seqs:
                    seq_to_id[s] = list(e.ids)

        conf, degraded = 0.95, False
        residuals = parsed.residuals
        if residuals:
            try:    # 残差>0 → LLM 二次解析（P-A1a）
                r = ctx.gateway.call("A1a", "P-A1a", {"residuals": residuals})
                for s, ids in (r.get("seq_to_id") or {}).items():
                    seq_to_id.setdefault(s, ids)
                conf = 0.8
            except Exception:
                degraded = True                          # 仍残差 → degraded 入抽样

        state.text_note = {
            "figure_id": state.figure_id,
            "seq_to_id": seq_to_id,
            "scales": parsed.scales,
            "note_type": parsed.note_type,
            "degraded": degraded,
            "residuals": residuals,
            "confidence": conf if seq_to_id else 0.0,
        }
        self.emit(state, "A1c", "text_note")
        return state

# -*- coding: utf-8 -*-
"""A8 质检仲裁：组装后质检，只降不升 fused 置信（与 A4 边界：A4=事前仲裁）。

回读不一致 → conf×0.7；<0.6 → review（interrupt）。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..errors import ErrorCode, ReviewRequired
from ..state import PairState


class A8QualityCheck(AgentInterface):
    name = "A8"
    timeout_s = 30
    prompt_deps = ["P-A8"]
    input_fields = ["pairs"]
    output_fields = []

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        for pair in state.pairs:
            # 单源 pair 加密抽检（方案 §4-A8）；双源+回读过高置信入库
            need_readback = (pair["provenance"]["source"] != "both"
                             or pair["confidence"] < 0.9)
            if need_readback:
                r = ctx.gateway.call("A8", "P-A8", {
                    "artifact_id": pair["artifact_id"],
                    "description": pair["description"][:512],   # 脱敏：截断
                    "line_drawing": pair["line_drawing"]})
                if not r.get("consistent", False):
                    pair["confidence"] = round(pair["confidence"] * 0.7, 3)  # 只降不升
            pair["state"] = "high_conf" if pair["confidence"] >= 0.9 else "draft"
            if pair["confidence"] < 0.6:
                pair["review_flag"] = True
        if any(p.get("review_flag") or p["confidence"] < 0.6 for p in state.pairs):
            raise ReviewRequired(ErrorCode.E_SEQ_UNRESOLVABLE, "qc",
                                 state.figure_id, "质检置信<0.6 或回读不一致，转人工")
        self.emit(state, "END", "pairs")
        return state

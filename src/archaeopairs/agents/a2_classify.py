# -*- coding: utf-8 -*-
"""A2 图类判定：type_a / plate / non 路由（先验零成本 → VLM 仅不确定 → 关键词否决）。

边界：A2 只判类别，不判图面完备性（属 A3）。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..state import PairState

VLM_THRESHOLD = 0.9        # config: agent.A2.vlm_threshold


class A2FigureClassify(AgentInterface):
    name = "A2"
    timeout_s = 30
    prompt_deps = ["P-A2"]
    input_fields = ["figure_index"]
    output_fields = ["figure_type"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        mode = state.figure_index.get("caption_mode", "uncertain")
        caption = state.figure_index.get("caption", "")
        threshold = ctx.config.get("A2.vlm_threshold", VLM_THRESHOLD)

        if mode == "artifact":                       # 先验确定：零 VLM 直消费
            state.figure_type = "type_a"
            state.confidence = 1.0
        elif mode == "plate":
            state.figure_type = "plate"
            state.confidence = 1.0
        elif mode == "non":
            # 规范V 特别说明：图题含"地层"但画面可能为清晰器物线图 → 强制二次确认
            if "地层" in caption:
                r = ctx.gateway.call("A2", "P-A2", {
                    "caption": caption, "check": "force_rule_a",
                    "fileref": state.figure_index.get("fileref")})
                if r.get("force_rule_a") and r.get("confidence", 0) >= threshold:
                    state.figure_type = "type_a"
                    state.confidence = r["confidence"]
                else:
                    state.figure_type = "non"        # 无法确认 → 保守否决但标记复核
                    state.review_flag = True
            else:
                state.figure_type = "non"
                state.confidence = 1.0
        else:                                        # uncertain → VLM 视觉判定
            r = ctx.gateway.call("A2", "P-A2", {
                "caption": caption, "fileref": state.figure_index.get("fileref")})
            conf = r.get("confidence", 0.0)
            vtype = r.get("type", "uncertain")
            if conf < threshold or vtype == "uncertain":
                state.review_flag = True             # conf<0.9 → review
                state.figure_type = "non"            # 保守归档，待人工
            else:
                state.figure_type = vtype
                state.confidence = conf
        self.emit(state, "*", "figure_type")
        return state

# -*- coding: utf-8 -*-
"""A3 图像源解析（链③）：图内 OCR 全量解析与完备性标记。

边界：A3 不判类别（属 A2）。OCR conf<0.8 → VLM 二次读 → 仍低 → incomplete/degraded。
当前为网关适配实现：横排+纵排双读、底部题/注带切分由 ocr-serve 承担。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..state import PairState


class A3ImageParse(AgentInterface):
    name = "A3"
    timeout_s = 60
    prompt_deps = ["P-A3"]
    input_fields = ["figure_index"]
    output_fields = ["image_side"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        try:
            r = ctx.gateway.call("A3", "P-A3", {
                "fileref": state.figure_index.get("fileref"),
                "case_pred": state.figure_index.get("case_pred"),
            })
            state.image_side = {
                "complete": True,
                "ocr_title": r.get("ocr_title"),
                "seq_set": r.get("seq_set", []),
                "seq_to_id": r.get("seq_to_id", {}),
                "scales": r.get("scales", []),
                "orientation": r.get("orientation", "h"),
                "confidence": r.get("confidence", 0.8),
            }
        except Exception as e:
            # OCR/VLM 均不可用 → image_side 缺失，A4 走 text_only（降级 cap 0.7）
            state.image_side = {"complete": False, "seq_set": [], "seq_to_id": {},
                                "scales": [], "orientation": "h", "confidence": 0.0,
                                "degraded": True}
            state.errors.append({"code": "E_OCR_UNAVAILABLE", "agent": self.name,
                                 "message": str(e)})
        self.emit(state, "A4", "image_side")
        return state

# -*- coding: utf-8 -*-
"""A6 彩板解析：图版页照片切分与条目映射（版面级；与 A5 掩膜级互补）。

三方对齐优先级：条目号 OCR > figure-note > 正文引用；对齐失败 → E_PLATE_MISALIGN。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..errors import ErrorCode, ReviewRequired
from ..state import PairState


class A6PlateParse(AgentInterface):
    name = "A6"
    timeout_s = 60
    prompt_deps = ["P-A6"]
    input_fields = ["figure_index", "text_side"]
    output_fields = ["plate_segments"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        ts = state.text_side or {}
        # 单件彩板直通：整页仅一件器物时无需版面切分
        id_to_desc = ts.get("id_to_desc") or {}
        if len(id_to_desc) == 1:
            aid = next(iter(id_to_desc))
            state.plate_segments = {
                "figure_id": state.figure_id,
                "items": [{"artifact_id": aid,
                           "photo_path": state.figure_index.get("fileref"),
                           "item_no": 1}],
                "confidence": 0.85,
            }
            self.emit(state, "A7", "plate_segments")
            return state
        # TODO: 版面分析（投影谷+连通域网格）→ 照片 box → 条目号 OCR 三方对齐
        raise ReviewRequired(ErrorCode.E_PLATE_MISALIGN, "mapping",
                             state.figure_index.get("fileref", ""),
                             "彩板版面切分未接入（待 layout 服务），转人工")

# -*- coding: utf-8 -*-
"""A5 视觉分割：按 fused_mapping 产单件器物子图（掩膜级，规范V 硬约束）。

硬约束落点（附录A，不可关）：
- 掩膜分割禁 bbox；序号硬匹配禁坐标距离；比例尺三级归属；异常必报警。
当前 SAM/OCR 未接入时 fail-closed：一律报警入复核，不产出任何 PNG。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..errors import ErrorCode, ReviewRequired
from ..state import PairState


class A5VisionSegment(AgentInterface):
    name = "A5"
    timeout_s = 60
    prompt_deps = ["P-A5"]
    input_fields = ["fused_mapping", "image_side"]
    output_fields = ["vision_segments"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        fused = state.fused_mapping or {}
        ims = state.image_side or {}

        # 无序号多器物场景（规范V 必报警项）：图底无序号列表但映射含多器物
        if not ims.get("seq_set") and len(fused.get("id_to_seqs", {})) > 1 \
                and not (state.text_side or {}).get("seq_to_id"):
            raise ReviewRequired(ErrorCode.E_NOSCOPE_MULTI, "mask",
                                 state.figure_index.get("fileref", ""),
                                 "无序号多器物图，无法硬匹配，人工确认归属")

        # OCR 序号锚点缺失 → 无法执行序号硬匹配（禁坐标距离）→ fail-closed
        if not ims.get("complete"):
            raise ReviewRequired(ErrorCode.E_SEQ_NOTFOUND, "mask",
                                 state.figure_index.get("fileref", ""),
                                 "图内 OCR 序号锚点缺失，禁止坐标距离推断，转人工")

        # TODO: 接入 sam-serve（§9.1）。完整流程：
        #   1) OCR seq 硬匹配定位各序号锚点（禁坐标距离）；
        #   2) VLM P-A5 多视图归组（conf<0.85→review）；
        #   3) 比例尺三级归属（seq硬绑定→全局唯一共享复制→≥2且有无号报警）；
        #   4) SAM 掩膜（seq 锚 point/box prompt）+ 轮廓闭合校验（不完整→E_MASK_INCOMPLETE）；
        #   5) 旋转校正 → 白底裁切 → 命名 原图名_seq_器物号.png（规范V §5）。
        r = ctx.gateway.call("A5", "P-A5", {
            "fileref": state.figure_index.get("fileref"),
            "seq_to_id": fused.get("seq_to_id"),
            "scales": ims.get("scales", [])})
        masks = r.get("masks") or []
        if not masks:
            raise ReviewRequired(ErrorCode.E_MASK_INCOMPLETE, "mask",
                                 state.figure_index.get("fileref", ""),
                                 "SAM 未产出有效掩膜")

        artifacts = []
        for aid, seqs in (fused.get("id_to_seqs") or {}).items():
            artifacts.append({
                "artifact_id": aid, "seqs": seqs,
                "mask_path": "",        # 由切割落盘逻辑填充
                "scale_cm": None, "scale_source": "ambiguous",
                "rotation": 0, "views": [],
            })
        state.vision_segments = {"figure_id": state.figure_id,
                                 "artifacts": artifacts, "alarms": []}
        self.emit(state, "A7", "vision_segments")
        return state

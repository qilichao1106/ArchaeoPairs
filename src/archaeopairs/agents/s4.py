"""S4 视觉分割器（§4.4）。Node: SAM 原子掩膜分割（轮廓引导提示点，禁 bbox）。

分割流程（§4.4.1）：OTSU 二值化 → 形态学膨胀 → 连通轮廓提取 → 孔洞剔除 →
逐轮廓采集正/负提示点调用 SAM（mode=prompt）→ 逐轮廓选 IoU 最优掩膜。
输出原子掩膜（MaskRecord：mask_rle/bbox/area，seq_id/artifact_id 留空待 S6 绑定；
P0 mock 实现按 ground 附带 seq_id 作便捷绑定提示）。

V0.5.4：SAM 分割职责自原 S6 移至 S4（E600 归属 S4）；原 S4 OCR 识别移至 S5。
"""
from __future__ import annotations

from ..errors import E006MaskIncompleteAlarm, HardConstraintError
from . import Services


def run(state: dict, svc: Services) -> dict:
    masks = svc.gateway.call(
        "sam", svc.sam.segment, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], prompts=[],
        operation="segment",
    )
    # 归一化为 MaskRecord 原子掩膜：seq_id 统一字符串（mock 便捷绑定提示）
    atoms: list[dict] = []
    for m in masks:
        m = dict(m)
        if not m.get("mask_rle"):
            # 硬约束：必须为掩膜，禁 bbox 矩形切割（附录 A 二篇 1）
            raise HardConstraintError("mask 必须为掩膜(RLE)，禁 bbox")
        if m.get("seq") is not None and m.get("seq_id") is None:
            m["seq_id"] = str(m.pop("seq"))
        elif m.get("seq_id") is not None:
            m["seq_id"] = str(m["seq_id"])
        atoms.append(m)
    if any(m.get("incomplete") for m in atoms):
        # E006 共享基准线致掩膜残缺（§6.3）：报警即停 → PENDING_REVIEW
        raise E006MaskIncompleteAlarm("shared baseline incomplete")
    # 纵横向检测（§4.4.2）：P0 由方向判定默认 'h'；生产实现文本方向分类后回填，
    # 多向时整图旋转 90°（rotation_correct 开关）并同步旋转掩膜/比例尺/说明文字。
    orientation = state.get("orientation") or "h"
    if svc.flags.rotation_correct and orientation == "v":
        for m in atoms:
            m["rotation"] = "cw"
    return {"atom_masks": atoms, "orientation": orientation, "status": "SEGMENTED"}

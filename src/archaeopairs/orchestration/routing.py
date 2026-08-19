"""条件边路由（条件边/路由表（§3.4.3）/ 图类判定器（§4.2）诊断驱动路由）。路由函数返回目标 Node 名。"""
from __future__ import annotations

from langgraph.graph import END

# 缺陷类型→回环目标分组（§3.4.3 路由表）：orientation_err 随 mask 缺陷组回 s6
# （整图旋转校正后重分割）；与文档 V0.5.2 §3.4.3 对齐。
_MASK_DEFECTS = {"under_seg", "over_seg", "mask_incomplete", "scale_mismatch", "orientation_err"}
_OCR_DEFECTS = {"seq_mismatch", "ocr_miss"}
_TEXT_DEFECTS = {"text_split_err"}
_GROUP_DEFECTS = {"group_error", "view_split"}


def route_s1(state: dict):
    if state.get("status") == "EXCLUDED":
        return END
    return "classify_figure"


def route_classify(state: dict):
    if state.get("status") in {"EXCLUDED"}:
        return [END]
    it = state.get("image_type")
    if it in {"single_line_artifact", "single_plate_artifact"}:
        return ["parse_single"]
    if it in {"multi_line_artifact"}:
        # V0.5.3 恢复多器物线图主通路：S2→S3/S4（平行）→S5→S6→S8→S9→S10
        return ["parse_text", "parse_image"]
    return [END]  # multi_plate_artifact / discarded


def route_assemble(state: dict):
    """S8 组装后分流：单器物整图即 Pair → S10；多器物线图 → S9 监督终检。"""
    if state.get("status") == "PENDING_REVIEW":
        return "bridge_review"  # 组装异常/未映射 → 复核
    if state.get("image_type") in {"single_line_artifact", "single_plate_artifact"}:
        return "bridge_review"  # 单器物：S8 → S10（不经 S9）
    return "supervise"  # 多器物线图：S8 → S9 Supervisor 监督终检


def route_single(state: dict):
    """单器物路径路由：EXCLUDED → 结束；PENDING_REVIEW → 复核；否则 → S8 组装。"""
    if state.get("status") == "EXCLUDED":
        return END
    if state.get("status") == "PENDING_REVIEW":
        return "bridge_review"
    return "assemble"


route_plate = route_single


def route_fuse(state: dict):
    if state.get("alarms"):
        return "bridge_review"
    if state.get("case_type") == "seq_missing" and not state.get("degraded"):
        return "bridge_review"
    return "segment"


def route_supervise(state: dict, max_iteration: int = 3, loop_enabled: bool = True):
    if state.get("status") == "PENDING_REVIEW" or state.get("alarms") or state.get("no_improve"):
        return "bridge_review"
    diag = state.get("diagnostic") or {}
    defects = {d.get("type") for d in diag.get("defect_list", [])}
    assembled = state.get("assembled", False)
    iteration = state.get("iteration", 0)
    if not defects:
        return "bridge_review" if assembled else "assemble"
    if not loop_enabled or iteration >= max_iteration:
        return "bridge_review"
    if defects & _MASK_DEFECTS:
        return "segment"
    if defects & _OCR_DEFECTS:
        return "parse_image"
    if defects & _TEXT_DEFECTS:
        return "parse_text"
    if defects & _GROUP_DEFECTS:
        return "assemble"
    return "bridge_review"

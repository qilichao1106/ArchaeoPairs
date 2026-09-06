"""条件边路由（条件边/路由表（§3.4.3）/ 图类判定器（§4.2））。路由函数返回目标 Node 名。

V0.5.4：多器物线图改串行 S3→S4→S5→S6；S9 纯质检门（route_qc）——合格经 S10
输出入库、不合格经 S10 转 Label Studio 复核，自动修正回环与迭代上限移除
（route_fuse/route_supervise 随之删除）。
"""
from __future__ import annotations

from langgraph.graph import END


def route_s1(state: dict):
    if state.get("status") == "EXCLUDED":
        return END
    return "s2_classify"


def route_classify(state: dict):
    if state.get("status") in {"EXCLUDED"}:
        return [END]
    it = state.get("image_type")
    if it in {"single_line_artifact", "single_plate_artifact"}:
        return ["s7_single"]
    if it in {"multi_line_artifact"}:
        # V0.5.4 串行主通路：S2→S3→S4→S5→S6→S8→S9→S10（S3 文本解析先行供链①②）
        return ["s3_text"]
    return [END]  # multi_plate_artifact / discarded


def route_compose(state: dict):
    """S6 组装后分流：报警即停 / seq_missing（E005）→ S10 复核桥接；否则 → S8 组装。"""
    if state.get("status") == "PENDING_REVIEW" or state.get("alarms"):
        return "s10_review"
    return "s8_assemble"


def route_assemble(state: dict):
    """S8 组装后分流：单器物整图即 Pair → S10；多器物线图 → S9 纯质检。"""
    if state.get("status") == "PENDING_REVIEW":
        return "s10_review"  # 组装异常/未映射 → 复核
    if state.get("image_type") in {"single_line_artifact", "single_plate_artifact"}:
        return "s10_review"  # 单器物：S8 → S10（不经 S9）
    return "s9_supervise"  # 多器物线图：S8 → S9 Supervisor 纯质检


def route_single(state: dict):
    """单器物路径路由：EXCLUDED → 结束；PENDING_REVIEW → 复核；否则 → S8 组装。"""
    if state.get("status") == "EXCLUDED":
        return END
    if state.get("status") == "PENDING_REVIEW":
        return "s10_review"
    return "s8_assemble"


route_plate = route_single


def route_qc(state: dict):
    """S9 纯质检路由（§3.4.3）：合格与不合格均进入 S10 两级分流——
    qc_verdict=pass → S10 输出 Pair 入库；reject → S10 转 Label Studio 复核
    （携带质检报告，不自动回环）。"""
    return "s10_review"

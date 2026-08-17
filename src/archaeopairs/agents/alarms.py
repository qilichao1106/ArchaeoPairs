"""硬约束报警检测与比例尺三级归属（对齐《技术方案 V0.3》异常报警字典（§6.3）/
序号硬匹配与比例尺三级（§5.3）/ 附录A 第二篇第4条（序号硬匹配））。

detect_alarms 返回触发的 E001–E007 编码；assign_scales 实现比例尺三级归属。
注意：figure-note 整图级缺失属降级场景（链②+③），不触发 E002/E005 硬报警。
"""
from __future__ import annotations

from typing import Iterable


def defect_target(defect_type: str) -> str:
    """缺陷类型→修正目标智能体（S3/S4/S6/S8），与路由表一致。"""
    if defect_type in {"under_seg", "over_seg", "mask_incomplete", "scale_mismatch"}:
        return "S6"
    if defect_type in {"seq_mismatch", "ocr_miss"}:
        return "S4"
    if defect_type == "text_split_err":
        return "S3"
    if defect_type in {"group_error", "view_split"}:
        return "S8"
    return "S6"


def _note_seqs(note_items: list[dict]) -> set[str]:
    out: set[str] = set()
    for it in note_items:
        for s in it.get("seq_list") or [it.get("seq")]:
            if s is not None:
                out.add(str(s))
    return out


def _ocr_seqs(seq_annotations: list[dict]) -> set[str]:
    return {str(a.get("text")) for a in seq_annotations}


def detect_alarms(state: dict) -> list[str]:
    note_items = state.get("note_items") or []
    seq_ann = state.get("seq_annotations") or []
    scales = state.get("scale_annotations") or []
    masks = state.get("masks") or []
    figure_note = state.get("figure_note")

    nseq = _note_seqs(note_items)
    oseq = _ocr_seqs(seq_ann)
    alarms: list[str] = []

    # E001 图注声明 seq 但图面无对应线图（链③存在时才可判定）
    if note_items and oseq and (nseq - oseq):
        alarms.append("E001")
    # E002 图面有序号线图但图注无对应声明（仅当图注存在时；整图缺失走降级）
    if figure_note and oseq and (oseq - nseq):
        alarms.append("E002")
    # E003 多个带序号比例尺无法与任一线图 seq 对应
    seqed = [s for s in scales if s.get("seq_ref")]
    if len(seqed) >= 2 and any(s["seq_ref"] not in (oseq | nseq) for s in seqed):
        alarms.append("E003")
    # E004 某比例尺无序号且全图多个比例尺（三级规则第三级）
    unseqed = [s for s in scales if not s.get("seq_ref")]
    if unseqed and len(scales) >= 2:
        alarms.append("E004")
    # E005 多器物但图注无序号列表（图注存在却解析不出序号）
    if figure_note and not nseq and (len(oseq) > 1 or len(masks) > 1):
        alarms.append("E005")
    # E006 共享基准线致掩膜残缺
    if any(m.get("incomplete") for m in masks):
        alarms.append("E006")
    return alarms


def assign_scales(scales: list[dict], seqs: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    """比例尺三级归属，返回 (scale_index->seq|'shared', 报警码)。"""
    seqs = set(seqs)
    alarms: list[str] = []
    out: dict[str, str] = {}
    if len(scales) == 1:                      # 二级：全局共享
        out["0"] = "shared"
        return out, alarms
    for i, s in enumerate(scales):            # 一级：硬性匹配
        ref = s.get("seq_ref")
        if ref and ref in seqs:
            out[str(i)] = ref
    unseqed = [i for i, s in enumerate(scales) if not s.get("seq_ref")]
    if unseqed and len(scales) >= 2:          # 三级：报警
        alarms.append("E004")
    return out, alarms

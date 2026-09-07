"""硬约束报警检测与比例尺三级归属（对齐《技术方案 V0.5.4》异常报警字典（§6.3）/
序号硬匹配与比例尺三级（§5.4）/ 附录A 第二篇第4条（序号硬匹配））。

detect_alarms 返回触发的 E001–E007 编码（由 S6 仲裁阶段统一检测）；
assign_scales 实现比例尺三级归属。V0.5.4 移除 defect_target（无修正回环，
不合格统一转人工复核）。注意：figure-note 整图级缺失属降级场景（链②+③），
不触发 E002/E005 硬报警。

V0.5.6：detect_alarms 增加 skip_scale 开关——S6 真实路径（_run_real）的比例尺
归属由 vision.assembly.bind_scales（L1/L2/L3+VL）执行，E003/E004 改由其
e4_alarms 经 _assembly_alarm_map 映射；此前真实路径仍全量跑 detect_alarms 再
在 s6 侧过滤 E003/E004（白算一次且按"全部 seq_ref=None"误报），现由调用方
传 skip_scale=True 直接跳过该段。assign_scales 明确标注 mock-only：仅供
_run_mock_path 使用，与 bind_scales 语义不等价，勿在真实链路调用。
"""
from __future__ import annotations

from typing import Iterable


def _note_seqs(note_items: list[dict]) -> set[str]:
    out: set[str] = set()
    for it in note_items:
        for s in it.get("seq_list") or [it.get("seq")]:
            if s is not None:
                out.add(str(s))
    return out


def _ocr_seqs(seq_annotations: list[dict]) -> set[str]:
    return {str(a.get("text")) for a in seq_annotations}


def detect_alarms(state: dict, *, skip_scale: bool = False) -> list[str]:
    """硬约束报警检测（E001–E006）。

    skip_scale=True（S6 真实路径）：跳过 E003/E004 比例尺段。该段基于
    scale_annotations.seq_ref 集合差判定，而真实路径的 seq_ref 由
    vision.assembly.bind_scales 在 E4 阶段才回填——检测时全为 None 会按
    "全部无序号"误报 E004；真实路径的比例尺报警改由 bind_scales 产出的
    e4_alarms 经 s6._assembly_alarm_map 映射（scale_unbound → E004）。
    默认 False 保持 mock 路径与既有调用方向后兼容。
    """
    note_items = state.get("note_items") or []
    seq_ann = state.get("seq_annotations") or []
    scales = state.get("scale_annotations") or []
    masks = state.get("atom_masks") or []
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
    if not skip_scale:
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


def assign_scales(scales: list[dict], seqs: Iterable[str]) -> tuple[dict[str, str], list[str]]:  # mock-only
    """比例尺三级归属（mock-only），返回 (scale_index->seq|'shared', 报警码)。

    ⚠ mock-only：仅供 S6 _run_mock_path（state.vision_units=None）使用。
    真实路径的比例尺归属由 vision.assembly.bind_scales 执行（L1 前缀序号
    硬匹配 > L2 唯一尺全局共享 > L3 VL 兜底读前缀），本函数只实现
    "seq_ref 硬匹配 + 单尺 shared + E004 报警"的契约级简化子集，无 L1
    前缀解析、无 L3 VL 兜底，两者语义不等价——勿在真实链路调用。
    """
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

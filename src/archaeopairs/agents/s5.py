"""S5 融合仲裁器（§4.5）。Node: 三链对齐→fused+case_type+报警（纯仲裁，不反推）。

整改：seq→多 artifact（同号/区间不截断）；链①⇄链③序号硬匹配与冲突检测；
按降级矩阵判定（图注整图缺失且链②/③可用→降级而非硬报警）。
配对一律按位置对应（zip）：多 seq 多 artifact 不展开笛卡尔积，
数量不一致时记入 conflicts（交由 S9 仲裁/人工复核），禁猜测。
"""
from __future__ import annotations

from typing import cast

from ..state import CaseType, FusedMapping
from . import Services
from .alarms import _note_seqs, _ocr_seqs, detect_alarms


def _case(note_items: list[dict]) -> str:
    if not note_items:
        return "seq_missing"
    arts = {a for it in note_items for a in it["artifact_ids"]}
    multi = any(len(it["artifact_ids"]) > 1 for it in note_items)
    has_range = any("~" in it["seq"] for it in note_items)  # seq 已经 normalize
    total_seqs = sum(len(it["seq_list"] or [it["seq"]]) for it in note_items)
    if multi and has_range:
        return "range_split"
    if multi:
        return "split_same_seq"
    if len(arts) == 1 and total_seqs > 1:
        return "rule_b"
    return "rule_a"


def _zip_seqs_arts(seqs: list, arts: list[str], conflicts: list[str]) -> list[tuple]:
    """位置对应配对（禁笛卡尔积）：
    * 等长 → zip；
    * 单 seq 多 artifact → 同号多器，逐 artifact 拆 Pair（共享掩膜）；
    * 多 seq 单 artifact → 同器多视图（rule_b 语义）；
    * 其余数量不一致 → 冲突登记，不猜测。
    """
    if len(seqs) == len(arts):
        return list(zip(seqs, arts))
    if len(seqs) == 1:
        return [(seqs[0], a) for a in arts]
    if len(arts) == 1:
        return [(s, arts[0]) for s in seqs]
    conflicts.append(f"seq_art_mismatch:seqs={seqs},arts={arts}")
    return []


def run(state: dict, svc: Services) -> dict:
    note_items = state.get("note_items", [])
    seq_ann = state.get("seq_annotations", [])
    text_art = state.get("text_artifacts", [])
    chains = (bool(note_items), bool(text_art), bool(seq_ann))

    alarms = detect_alarms(state)
    case = cast(CaseType, _case(note_items))

    # seq -> [artifacts]（多值，不截断；位置对应）
    conflicts: list[str] = []
    seq_to_arts: dict[str, list[str]] = {}
    for it in note_items:
        seqs = it["seq_list"] or [it["seq"]]
        for s, a in _zip_seqs_arts(list(seqs), list(it["artifact_ids"]), conflicts):
            seq_to_arts.setdefault(str(s), []).append(a)

    # 链① vs 链③ 冲突
    if note_items and seq_ann:
        nseq, oseq = _note_seqs(note_items), _ocr_seqs(seq_ann)
        conflicts.extend(sorted(nseq ^ oseq))

    key = "".join("1" if c else "0" for c in chains)
    conf_map = {"111": 0.95, "110": 0.85, "101": 0.85, "100": 0.85,
                "011": 0.70, "010": 0.60, "001": 0.50}
    conf = conf_map.get(key, 0.5)
    # 图注整图缺失但有链②/③ → 降级（不硬报警），置信封顶
    degraded = (not note_items) and (bool(text_art) or bool(seq_ann))
    fused = FusedMapping(seq_to_artifacts=seq_to_arts, case_type=case,
                         available_chains=chains, confidence=conf, conflicts=conflicts)
    return {"fused": fused.model_dump(), "case_type": case, "confidence": conf,
            "alarms": alarms, "degraded": degraded, "status": "ALIGNED"}

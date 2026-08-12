"""S5 融合仲裁器（§4.5）。Node: 三链对齐→fused+case_type+报警（纯仲裁，不反推）。

整改：seq→多 artifact（同号/区间不截断）；链①⇄链③序号硬匹配与冲突检测；
按降级矩阵判定（图注整图缺失且链②/③可用→降级而非硬报警）。
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
    has_range = any(("~" in it["seq"]) or ("-" in it["seq"]) for it in note_items)
    total_seqs = sum(len(it["seq_list"] or [it["seq"]]) for it in note_items)
    if multi:
        return "range_split" if has_range else "split_same_seq"
    if len(arts) == 1 and total_seqs > 1:
        return "rule_b"
    return "rule_a"


def run(state: dict, svc: Services) -> dict:
    note_items = state.get("note_items", [])
    seq_ann = state.get("seq_annotations", [])
    text_art = state.get("text_artifacts", [])
    chains = (bool(note_items), bool(text_art), bool(seq_ann))

    alarms = detect_alarms(state)
    case = cast(CaseType, _case(note_items))

    # seq -> [artifacts]（多值，不截断）
    seq_to_arts: dict[str, list[str]] = {}
    if case in ("rule_a", "rule_b"):
        for it in note_items:
            for s in (it["seq_list"] or [it["seq"]]):
                if it["artifact_ids"]:
                    seq_to_arts.setdefault(str(s), []).extend(it["artifact_ids"])
    elif case == "split_same_seq":
        # 同号多器：同一 seq 对应全部 artifact（不截断）
        for it in note_items:
            for s in (it["seq_list"] or [it["seq"]]):
                seq_to_arts.setdefault(str(s), []).extend(it["artifact_ids"])
    elif case == "range_split":
        # 区间：seq 与 artifact 按位置对应
        for it in note_items:
            seqs = it["seq_list"] or [it["seq"]]
            for s, a in zip(seqs, it["artifact_ids"]):
                seq_to_arts.setdefault(str(s), []).append(a)

    # 链① vs 链③ 冲突
    conflicts: list[str] = []
    if note_items and seq_ann:
        nseq, oseq = _note_seqs(note_items), _ocr_seqs(seq_ann)
        conflicts = sorted(nseq ^ oseq)

    key = "".join("1" if c else "0" for c in chains)
    conf_map = {"111": 0.95, "110": 0.85, "101": 0.85, "011": 0.70, "010": 0.60, "001": 0.50}
    conf = conf_map.get(key, 0.5)
    # 图注整图缺失但有链②/③ → 降级（不硬报警），置信封顶
    degraded = (not note_items) and (bool(text_art) or bool(seq_ann))
    fused = FusedMapping(seq_to_artifacts=seq_to_arts, case_type=case,
                         available_chains=chains, confidence=conf, conflicts=conflicts)
    return {"fused": fused.model_dump(), "case_type": case, "confidence": conf,
            "alarms": alarms, "degraded": degraded, "status": "ALIGNED"}

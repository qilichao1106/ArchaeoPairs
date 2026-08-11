"""S5 融合仲裁器（§4.5）。Node: 三链对齐→fused_mapping+case_type（纯仲裁，不反推）。"""
from __future__ import annotations

from ..state import FusedMapping
from . import Services


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

    case = _case(note_items)
    seq_to_art: dict[str, str] = {}
    if case in ("rule_a", "rule_b"):
        for it in note_items:
            for s in (it["seq_list"] or [it["seq"]]):
                if it["artifact_ids"]:
                    seq_to_art[str(s)] = it["artifact_ids"][0]
    elif case in ("split_same_seq", "range_split"):
        for it in note_items:
            seqs = it["seq_list"] or [it["seq"]]
            for s, a in zip(seqs, it["artifact_ids"]):
                seq_to_art[str(s)] = a

    key = "".join("1" if c else "0" for c in chains)
    conf_map = {"111": 0.95, "110": 0.85, "101": 0.85, "011": 0.70, "010": 0.60, "001": 0.50}
    conf = conf_map.get(key, 0.5)
    fused = FusedMapping(seq_to_artifact=seq_to_art, case_type=case,
                         available_chains=chains, confidence=conf)
    return {"fused": fused.model_dump(), "case_type": case, "confidence": conf,
            "status": "ALIGNED"}

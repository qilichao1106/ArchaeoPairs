# -*- coding: utf-8 -*-
"""A1c 文本源聚合：按 figure 聚合 A1a（图注）+ A1b（正文引用）→ text_side。

置信度（方案 §4-A1c）：双成功→min(A1a,A1b)；仅 A1a→cap 0.7；仅 A1b→cap 0.6；
双失败→E_TEXT_SIDE_MISSING（A4 走 image_only）。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..errors import ErrorCode
from ..state import PairState


class A1cTextAggregate(AgentInterface):
    name = "A1c"
    timeout_s = 10
    input_fields = ["text_note", "artifact_records"]
    output_fields = ["text_side"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        note = state.text_note or {}
        seq_to_id: dict[str, list[str]] = dict(note.get("seq_to_id") or {})
        note_conf = note.get("confidence", 0.0)
        note_ok = bool(seq_to_id)

        id_to_desc: dict[str, str] = {}
        id_to_name: dict[str, str] = {}
        ref_seqs: dict[str, list[int]] = {}
        for rec in state.artifact_records or []:
            id_to_desc[rec["artifact_id"]] = rec["description"]
            id_to_name[rec["artifact_id"]] = rec.get("name", "")
            ref_seqs[rec["artifact_id"]] = rec.get("ref_seqs", [])
        body_ok = bool(id_to_desc)

        # 交叉验证：A1b 引用 seq 与 A1a seq_to_id 比对，冲突入 conflicts
        conflicts: list[dict] = []
        for aid, seqs in ref_seqs.items():
            for s in seqs:
                key = str(s)
                if key in seq_to_id and aid not in seq_to_id[key]:
                    conflicts.append({"seq": key, "note_ids": seq_to_id[key],
                                      "body_id": aid})

        if note_ok and body_ok:
            conf = min(note_conf, 0.95)
            degraded = note.get("degraded", False)
        elif note_ok:
            conf, degraded = min(note_conf, 0.7), True
        elif body_ok:
            conf, degraded = 0.6, True
        else:
            conf, degraded = 0.0, True
            state.errors.append({"code": ErrorCode.E_TEXT_SIDE_MISSING.value,
                                 "agent": self.name,
                                 "message": "双文本源均失败，A4 将走 image_only"})

        state.text_side = {
            "figure_id": state.figure_id,
            "seq_set": sorted(seq_to_id.keys(), key=lambda x: int(x)),
            "seq_to_id": seq_to_id,
            "id_to_desc": id_to_desc,
            "id_to_name": id_to_name,
            "degraded": degraded,
            "note_provenance": "both" if (note_ok and body_ok)
                               else ("note_only" if note_ok else
                                     ("body_only" if body_ok else "none")),
            "conflicts": conflicts,
            "confidence": conf,
        }
        self.emit(state, "A4", "text_side")
        return state

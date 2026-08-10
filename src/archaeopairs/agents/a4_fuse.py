# -*- coding: utf-8 -*-
"""A4 融合仲裁：对齐 text_side 与 image_side 的 seq→ids，产 fused_mapping+provenance。

决策表（方案 §4-A4 / prompts/P-A4.md，确定性优先、VLM 仅仲裁冲突残差）：
- 完全一致 → source=both, conf 0.95
- 交集非空部分一致 → conf 0.85, flag=partial
- 仅图注有/仅正文有 → 单源, conf 0.7
- 冲突 → VLM 仲裁（P-A4）→ 0.75, flag=vlm_arbitrated
- 仍不可解 → conf 0, 入 review（禁猜测配对）
规则B：同一器物号下多 seq → case_type=rule_b（合并一张子图，禁拆）。
"""
from __future__ import annotations

from ..agent import AgentInterface, AgentContext
from ..state import PairState


class A4FuseArbitrate(AgentInterface):
    name = "A4"
    timeout_s = 30
    prompt_deps = ["P-A4"]
    input_fields = ["text_side", "image_side"]
    output_fields = ["fused_mapping"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        ts, ims = state.text_side or {}, state.image_side or {}
        t_map: dict[str, list[str]] = ts.get("seq_to_id") or {}
        i_map: dict[str, list[str]] = ims.get("seq_to_id") or {}
        i_ok = bool(i_map) and ims.get("complete", False)

        fused: dict[str, list[str]] = {}
        prov: dict[str, dict] = {}
        flags: list[str] = []
        confs: list[float] = []

        all_seqs = sorted(set(t_map) | set(i_map), key=lambda x: int(x))
        for seq in all_seqs:
            t_ids, i_ids = set(t_map.get(seq, [])), set(i_map.get(seq, []))
            if t_ids and i_ok and i_ids:
                if t_ids == i_ids:                          # 完全一致
                    fused[seq] = sorted(t_ids)
                    prov[seq] = {"source": "both", "agents": ["A1a", "A1b", "A3"],
                                 "confidence": 0.95}
                elif t_ids & i_ids:                         # 部分一致
                    fused[seq] = sorted(t_ids & i_ids)
                    prov[seq] = {"source": "both", "agents": ["A1a", "A1b", "A3"],
                                 "confidence": 0.85, "flag": "partial"}
                    flags.append(f"partial:{seq}")
                else:                                       # 冲突 → VLM 仲裁
                    arb = ctx.gateway.call("A4", "P-A4", {
                        "figure_no": state.figure_index.get("figure_no", {}).get("norm"),
                        "note_side": {seq: sorted(t_ids)},
                        "image_side": {seq: sorted(i_ids)}})
                    a_ids = (arb.get("seq_to_id") or {}).get(seq)
                    if a_ids:
                        fused[seq] = a_ids
                        prov[seq] = {"source": "vlm_arbitrated", "agents": ["A4"],
                                     "confidence": 0.75, "flag": "vlm_arbitrated"}
                        flags.append(f"vlm_arbitrated:{seq}")
                    else:                                   # 不可解 → review
                        prov[seq] = {"source": "unresolvable", "agents": ["A4"],
                                     "confidence": 0.0}
                        flags.append(f"unresolvable:{seq}")
            elif t_ids:                                     # 单源：text_only
                fused[seq] = sorted(t_ids)
                prov[seq] = {"source": "note_only" if ts.get("note_provenance") != "body_only"
                             else "body_only",
                             "agents": ["A1a", "A1b"], "confidence": 0.7}
                flags.append(f"single_source:{seq}")
            else:                                           # 单源：image_only
                fused[seq] = sorted(i_ids)
                prov[seq] = {"source": "image_only", "agents": ["A3"],
                             "confidence": 0.7}
                flags.append(f"single_source:{seq}")

        # 规则B 判定：同一器物号出现多个 seq → 同器物多视图，合并一张子图
        id_seqs: dict[str, list[str]] = {}
        for seq, ids in fused.items():
            for aid in ids:
                id_seqs.setdefault(aid, []).append(seq)
        case_type = "rule_b" if any(len(v) > 1 for v in id_seqs.values()) else "rule_a"

        confs = [p["confidence"] for p in prov.values()]
        review = (any(p["source"] == "unresolvable" for p in prov.values())
                  or any(f.startswith("vlm_arbitrated") for f in flags))
        overall = min(confs) if confs else 0.0

        state.fused_mapping = {
            "figure_id": state.figure_id,
            "case_type": case_type,
            "seq_to_id": fused,
            "id_to_seqs": id_seqs,
            "per_elem_provenance": prov,
            "conflict_flags": flags,
            "confidence": overall,
            "review_flag": review,
        }
        state.review_flag = state.review_flag or review
        self.emit(state, "A5", "fused_mapping")
        return state

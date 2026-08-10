# -*- coding: utf-8 -*-
"""A7 匹配组装：Pair 组装、同号拆 Pair、provenance 落盘、原子写。

要点：
- join 键 artifact_id / (figure, seq)；同号 ids 拆独立 Pair 共享 mask 路径；
- pair.schema.json 轻量校验（必填字段 + 归一化器物号形态）；违例 → halt；
- tmp+rename 原子写：崩溃恢复不产生半份 Pair（§6.3）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..agent import AgentInterface, AgentContext
from ..errors import AgentError, ErrorCode, ReviewRequired
from ..regexes import ARTIFACT_ID_NORM_RE
from ..state import PairState

REQUIRED = ["artifact_id", "description", "line_drawing", "case_type",
            "provenance", "confidence", "state", "idem_key", "trace_id"]


def _validate_pair(pair: dict) -> None:
    missing = [k for k in REQUIRED if k not in pair]
    if missing:
        raise AgentError(ErrorCode.E_SCHEMA_VIOLATION,
                         f"pair 缺必填字段: {missing}", fatal=True)
    if not ARTIFACT_ID_NORM_RE.match(pair["artifact_id"]):
        raise AgentError(ErrorCode.E_SCHEMA_VIOLATION,
                         f"器物号未归一化: {pair['artifact_id']}", fatal=True)
    if not pair["description"]:
        raise AgentError(ErrorCode.E_KEY_MISSING, "description 为空", fatal=False)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)                    # 同分区 rename 原子语义


class A7Assemble(AgentInterface):
    name = "A7"
    timeout_s = 10
    input_fields = ["fused_mapping", "vision_segments", "plate_segments", "text_side"]
    output_fields = ["pairs"]

    def run(self, state: PairState, ctx: AgentContext) -> PairState:
        fused = state.fused_mapping or {}
        ts = state.text_side or {}
        id_to_desc: dict[str, str] = ts.get("id_to_desc") or {}
        id_to_name: dict[str, str] = ts.get("id_to_name") or {}
        vs = state.vision_segments or {}
        ps = state.plate_segments or {}

        mask_by_id = {a["artifact_id"]: a for a in vs.get("artifacts", [])}
        photo_by_id = {i["artifact_id"]: i for i in ps.get("items", [])}
        prov_map = fused.get("per_elem_provenance", {})

        pairs: list[dict] = []
        for aid, seqs in (fused.get("id_to_seqs") or {}).items():
            if aid not in id_to_desc:
                raise ReviewRequired(ErrorCode.E_KEY_MISSING, "mapping",
                                     aid, f"器物号 {aid} 无正文描述，键缺失")
            # provenance 聚合：取该器物各 seq 的最低置信与最强来源
            seq_provs = [prov_map.get(s, {}) for s in seqs]
            conf = min((p.get("confidence", 0.0) for p in seq_provs), default=0.0)
            sources = {p.get("source", "") for p in seq_provs}
            source = "both" if "both" in sources else (
                "vlm_arbitrated" if "vlm_arbitrated" in sources else
                next(iter(sources - {""}), "note_only"))
            seg = mask_by_id.get(aid, {})
            plate = photo_by_id.get(aid)
            pair = {
                "artifact_id": aid,
                "original_id": aid,
                "description": id_to_desc[aid],
                "line_drawing": seg.get("mask_path", ""),
                "plate_photo": plate["photo_path"] if plate else None,
                "image_meta": {
                    "figure_no": state.figure_index.get("figure_no", {}).get("norm", ""),
                    "caption": state.figure_index.get("caption", ""),
                    "note_text": state.figure_index.get("note_text", ""),
                },
                "case_type": "plate" if plate and not seg else fused.get("case_type", "rule_a"),
                "provenance": {"source": source,
                               "agents": sorted({a for p in seq_provs
                                                 for a in p.get("agents", [])})},
                "confidence": conf,
                "review_flag": state.review_flag,
                "state": "draft",
                "idem_key": state.idem_key,
                "trace_id": state.trace_id,
                "name": id_to_name.get(aid, ""),
            }
            _validate_pair(pair)
            pairs.append(pair)

        # 落盘：data/<book_id>/pairs/<figure_id>.json（原子写）
        out = Path(ctx.book_dir) / "pairs" / f"{state.figure_id}.json"
        _atomic_write(out, json.dumps(pairs, ensure_ascii=False, indent=2))
        state.pairs = pairs
        self.emit(state, "A8", "pairs")
        return state

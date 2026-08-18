"""S8 匹配组装器（§4.8）。Node: 按 fused 拆/并 mask→PairRecord（确定性）。

整改：seq→多 artifact 全量拆 Pair（同号/区间不丢数据）；命名按图号提取+冒号
归一+_N 去重（文件命名规范（§7.2））；经合成器写对象存储；无映射 mask 不静默丢弃（转复核）。

V0.3/V0.4 单器物路径：整图单一器物 → 单个 PairRecord（single_artifacts 驱动），
seq 段以 01 占位（单器物命名占位判断）；跨图合并不在 V0.4 范围（按单图独立输出）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from .. import naming
from ..state import PairRecord
from . import Services

_MergeMode = Literal["line_only", "plate_only", "line_plus_plate", "multi_candidate"]


def _assemble_single(state: dict, svc: Services, single_artifacts: list[dict]) -> dict:
    """S8 single-artifact assembly (V0.4 §4.8): whole image -> one PairRecord."""
    book_id = state["book_id"]
    registry: dict[str, int] = svc.name_registry
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}
    fallback_fig = naming.extract_fig_number(state.get("caption"),
                                               fallback=Path(state["fileref"]).stem)
    records: list[dict] = []
    for item in single_artifacts:
        art = item["artifact_id"]
        role = item.get("role", "line_drawing")
        merge_mode: _MergeMode = cast(
            _MergeMode,
            item.get("image_merge_mode")
            or ("plate_only" if role == "plate" else "line_only"))
        fig_number = item.get("fig_number") or fallback_fig
        name = naming.dedup_name(naming.build_image_name(fig_number, None, art), registry)
        if svc.compositor is not None and svc.object_store is not None:
            svc.compositor.compose(image_path=name, masks=[], trace_id=state["trace_id"])
        records.append(PairRecord(
            book_id=book_id, artifact_id=art, image_path=name,
            candidate_images=[],
            image_merge_mode=merge_mode,
            description_text=desc.get(art),
            provenance={"case": state.get("case_type"), "art_source": item.get("source"),
                        "single": True, "whole_image": True, "role": role,
                        "figure_id": item.get("figure_id")},
        ).model_dump())
    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}




def run(
    state: dict, svc: Services) -> dict:
    single = state.get("single_artifacts") or []
    if single:
        return _assemble_single(state, svc, single)

    fused = state.get("fused") or {}
    seq_to_arts: dict[str, list[str]] = fused.get("seq_to_artifacts", {})
    # 图题兜底器物号（§2.2.5）：图注无器物号时由 S5 仲裁采用，rule_b 整图归属
    caption_arts: set[str] = set(fused.get("caption_artifacts", []))
    note_arts: set[str] = {a for lst in seq_to_arts.values() for a in lst}
    case = state.get("case_type")
    masks = state.get("masks", [])
    book_id = state["book_id"]
    fig_number = naming.extract_fig_number(state.get("caption"),
                                           fallback=Path(state["fileref"]).stem)
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}
    # book 级共享去重注册表：跨图同图号同器物防文件名冲突（文件命名规范（§7.2）重名 _N）
    registry: dict[str, int] = svc.name_registry
    records: list[dict] = []
    unmatched = [m.get("seq") for m in masks
                 if m.get("seq") is not None and str(m.get("seq")) not in seq_to_arts]
    if unmatched and case != "rule_b":
        return {"pair_records": [], "assembled": True, "status": "PENDING_REVIEW",
                "alarms": ["E002"], "exclude_reason": "unmapped_mask"}

    def _emit(art: str, seq: str | None, ms: list[dict], views: int) -> None:
        name = naming.build_image_name(fig_number, seq, art)
        name = naming.dedup_name(name, registry)
        if svc.compositor is not None and svc.object_store is not None:
            svc.compositor.compose(image_path=name, masks=ms, trace_id=state["trace_id"])
        art_source = "caption" if (art in caption_arts and art not in note_arts) else "figure_note"
        records.append(PairRecord(
            book_id=book_id, artifact_id=art, image_path=name,
            candidate_images=[],
            image_merge_mode="line_only",
            description_text=desc.get(art),
            provenance={"case": case, "seqs": [m.get("seq") for m in ms], "views": views,
                        "art_source": art_source},
        ).model_dump())

    if case == "rule_b":
        arts = note_arts | caption_arts
        if arts:
            art = next(iter(arts))
            _emit(art, None, masks, views=len(masks))
    else:
        for m in masks:
            art_list = seq_to_arts.get(str(m.get("seq")), [])
            for art in art_list:
                _emit(art, str(m.get("seq")), [m], views=1)

    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

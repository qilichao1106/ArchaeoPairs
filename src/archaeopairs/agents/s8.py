"""S8 匹配组装器（§4.8）。Node: 按 fused 拆/并 mask→PairRecord（确定性）。

整改：seq→多 artifact 全量拆 Pair（同号/区间不丢数据）；命名按图号提取+冒号
归一+_N 去重（文件命名规范（§7.2））；经合成器写对象存储；无映射 mask 不静默丢弃（转复核）。

真实组级发射（V0.5.4，state.view_groups 置位时）：一组（多视图器物）一次
compose 产 1 张 PNG（对齐原型 <stem>_<seq>.png 语义），render_ctx 随组透传
PixelCompositor 纯像素渲染；多器物共组逐 artifact 拆 Pair（共享组画面）；
组 seq 无 artifact 映射不静默丢弃（转复核，与 mock 路径一致）。

V0.3/V0.4 单器物路径：整图单一器物 → 单个 PairRecord（single_artifacts 驱动），
seq 段以 01 占位（单器物命名占位判断）；跨图合并不在当前版本（V0.5.1）范围（按单图独立输出）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from .. import naming
from ..state import PairRecord
from . import Services

_MergeMode = Literal["line_only", "plate_only", "line_plus_plate", "multi_candidate"]


def _assemble_single(state: dict, svc: Services, single_artifacts: list[dict]) -> dict:
    """S8 single-artifact assembly (V0.5.1 §4.8): whole image -> one PairRecord."""
    book_id = state["book_id"]
    registry: dict[str, int] = svc.name_registry
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}
    fallback_fig = naming.extract_fig_number(state.get("caption"),
                                               fallback=Path(state["fileref"]).stem)
    # 源图（整图即 Pair → 拷贝原 media 图，而非白底占位）
    source = _resolve_source(state)
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
            svc.compositor.compose(image_path=name, masks=[], trace_id=state["trace_id"],
                                   source=source)
        records.append(PairRecord(
            book_id=book_id, figure_id=state["figure_id"], artifact_id=art, image_path=name,
            candidate_images=[],
            image_merge_mode=merge_mode,
            description_text=desc.get(art),
            provenance={"case": state.get("case_type"), "art_source": item.get("source"),
                        "single": True, "whole_image": True, "role": role,
                        "figure_id": item.get("figure_id")},
        ).model_dump())
    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}




def _resolve_source(state: dict) -> str | None:
    """源图绝对路径（image_base/fileref；真实像素合成按组贴原图像素）。"""
    if state.get("image_base") and state.get("fileref"):
        _s = Path(state["image_base"]) / state["fileref"]
        if _s.is_file():
            return str(_s)
    return None


def _assemble_groups(state: dict, svc: Services) -> dict:
    """真实组级发射（V0.5.4）：一组多视图器物 → 1 张 PNG / 1+ PairRecord。"""
    fused = state.get("fused") or {}
    seq_to_arts: dict[str, list[str]] = fused.get("seq_to_artifacts", {})
    caption_arts: set[str] = set(fused.get("caption_artifacts", []))
    note_arts = {a for lst in seq_to_arts.values() for a in lst}
    case = state.get("case_type")
    masks = state.get("atom_masks", [])
    groups = state.get("view_groups") or []
    book_id = state["book_id"]
    fig_number = naming.extract_fig_number(state.get("caption"),
                                           fallback=Path(state["fileref"]).stem)
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}
    registry: dict[str, int] = svc.name_registry
    source = _resolve_source(state)
    records: list[dict] = []

    # 组 seq 无 artifact 映射不静默丢弃（转复核；rule_b 整图归属除外）
    if case != "rule_b":
        for g in groups:
            if any(str(s) not in seq_to_arts for s in (g.get("seq_ids") or [])):
                return {"pair_records": [], "assembled": True,
                        "status": "PENDING_REVIEW", "alarms": ["E002"],
                        "exclude_reason": "unmapped_mask"}

    for g in groups:
        seqs = [str(s) for s in (g.get("seq_ids") or [])]
        arts: list[str] = []
        for s in seqs:
            for a in seq_to_arts.get(s, []):
                if a not in arts:
                    arts.append(a)
        if not arts:
            # rule_b 兜底 / 图题器物号兜底（§2.2.5）：整图归属该器
            pool = note_arts | caption_arts
            arts = [next(iter(pool))] if pool else []
        if not arts:
            continue                     # 无任何器物映射：不发射（留待复核）
        ms = [masks[i] for i in (g.get("mask_idxs") or []) if i < len(masks)]
        seq_tag = ",".join(seqs) if len(seqs) > 1 else (seqs[0] if seqs else None)
        for art in arts:
            name = naming.dedup_name(
                naming.build_image_name(fig_number, seq_tag, art), registry)
            if svc.compositor is not None and svc.object_store is not None:
                svc.compositor.compose(image_path=name, masks=ms,
                                       trace_id=state["trace_id"], source=source,
                                       render_ctx=g.get("render"))
            art_source = "caption" if (art in caption_arts
                                       and art not in note_arts) else "figure_note"
            records.append(PairRecord(
                book_id=book_id, figure_id=state["figure_id"],
                artifact_id=art, image_path=name, candidate_images=[],
                image_merge_mode="line_only",
                description_text=desc.get(art),
                provenance={"case": case, "seqs": seqs, "views": len(ms),
                            "group_id": g.get("group_id"),
                            "scale_sis": g.get("scale_sis"),
                            "art_source": art_source},
            ).model_dump())

    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}


def run(
    state: dict, svc: Services) -> dict:
    single = state.get("single_artifacts") or []
    if single:
        return _assemble_single(state, svc, single)

    # 真实组级发射（S6 真实组装写回 view_groups）；mock 路径不置 → 逐 mask
    if state.get("view_groups"):
        return _assemble_groups(state, svc)

    fused = state.get("fused") or {}
    seq_to_arts: dict[str, list[str]] = fused.get("seq_to_artifacts", {})
    # 图题兜底器物号（§2.2.5）：图注无器物号时由 S5 仲裁采用，rule_b 整图归属
    caption_arts: set[str] = set(fused.get("caption_artifacts", []))
    note_arts: set[str] = {a for lst in seq_to_arts.values() for a in lst}
    case = state.get("case_type")
    masks = state.get("atom_masks", [])
    book_id = state["book_id"]
    fig_number = naming.extract_fig_number(state.get("caption"),
                                           fallback=Path(state["fileref"]).stem)
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}
    # book 级共享去重注册表：跨图同图号同器物防文件名冲突（文件命名规范（§7.2）重名 _N）
    registry: dict[str, int] = svc.name_registry
    records: list[dict] = []
    unmatched = [m.get("seq_id") for m in masks
                 if m.get("seq_id") is not None and str(m.get("seq_id")) not in seq_to_arts]
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
            book_id=book_id, figure_id=state["figure_id"], artifact_id=art, image_path=name,
            candidate_images=[],
            image_merge_mode="line_only",
            description_text=desc.get(art),
            provenance={"case": case, "seqs": [m.get("seq_id") for m in ms], "views": views,
                        "art_source": art_source},
        ).model_dump())

    if case == "rule_b":
        arts = note_arts | caption_arts
        if arts:
            art = next(iter(arts))
            _emit(art, None, masks, views=len(masks))
    else:
        for m in masks:
            art_list = seq_to_arts.get(str(m.get("seq_id")), [])
            for art in art_list:
                _emit(art, str(m.get("seq_id")), [m], views=1)

    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

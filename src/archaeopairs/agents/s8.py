"""S8 匹配组装器（§4.8）。Node: 按 fused 拆/并 mask→PairRecord（确定性）。

整改：seq→多 artifact 全量拆 Pair（同号/区间不丢数据）；命名按图号提取+冒号
归一+_N 去重（§7.2）；经合成器写对象存储；无映射 mask 不静默丢弃（转复核）。
"""
from __future__ import annotations

from pathlib import Path

from .. import naming
from ..state import PairRecord
from . import Services


def run(state: dict, svc: Services) -> dict:
    fused = state.get("fused") or {}
    seq_to_arts: dict[str, list[str]] = fused.get("seq_to_artifacts", {})
    case = state.get("case_type")
    masks = state.get("masks", [])
    book_id = state["book_id"]
    fig_number = naming.extract_fig_number(state.get("caption"),
                                           fallback=Path(state["fileref"]).stem)
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}
    # book 级共享去重注册表：跨图同图号同器物防文件名冲突（§7.2 重名 _N）
    registry: dict[str, int] = svc.name_registry
    records: list[dict] = []
    unmatched = [m.get("seq") for m in masks
                 if m.get("seq") is not None and str(m.get("seq")) not in seq_to_arts]
    if unmatched:
        return {"pair_records": [], "assembled": True, "status": "PENDING_REVIEW",
                "alarms": ["E002"], "exclude_reason": "unmapped_mask"}

    def _emit(art: str, seq: str | None, ms: list[dict], views: int) -> None:
        name = naming.build_image_name(fig_number, seq, art)
        name = naming.dedup_name(name, registry)
        if svc.compositor is not None and svc.object_store is not None:
            svc.compositor.compose(image_path=name, masks=ms, trace_id=state["trace_id"])
        records.append(PairRecord(
            book_id=book_id, artifact_id=art, image_path=name,
            candidate_images=[],
            image_merge_mode="line_only",
            description_text=desc.get(art),
            provenance={"case": case, "seqs": [m.get("seq") for m in ms], "views": views},
        ).model_dump())

    if case == "rule_b":
        arts = {a for lst in seq_to_arts.values() for a in lst}
        if arts:
            art = next(iter(arts))
            _emit(art, None, masks, views=len(masks))
    else:
        for m in masks:
            art_list = seq_to_arts.get(str(m.get("seq")), [])
            for art in art_list:
                _emit(art, str(m.get("seq")), [m], views=1)

    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

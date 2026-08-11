"""S8 匹配组装器（§4.8）。Node: 按 fused_mapping 拆/并 mask→PairRecord（确定性）。"""
from __future__ import annotations

from ..state import PairRecord
from . import Services


def run(state: dict, svc: Services) -> dict:
    fused = state.get("fused") or {}
    seq_to_art = fused.get("seq_to_artifact", {})
    case = state.get("case_type")
    masks = state.get("masks", [])
    book_id = state["book_id"]

    # mask → artifact 归组
    by_art: dict[str, list[dict]] = {}
    for m in masks:
        art = seq_to_art.get(str(m.get("seq")), ) or (m.get("artifact_id"))
        if art is None:
            continue
        by_art.setdefault(art, []).append(m)

    # 描述文本（链②）
    desc = {t["artifact_id"]: t["text"] for t in state.get("text_artifacts", [])}

    records: list[dict] = []
    if case in ("rule_b",) and by_art:
        # 单器物多视图合并为一张
        art = next(iter(by_art))
        records.append(PairRecord(
            book_id=book_id, artifact_id=art,
            image_path=f"{state['fileref']}_{art.replace(':', '-')}.png",
            description_text=desc.get(art),
            provenance={"case": case, "views": len(by_art[art])},
        ).model_dump())
    else:
        for art, ms in by_art.items():
            records.append(PairRecord(
                book_id=book_id, artifact_id=art,
                image_path=f"{state['fileref']}_{ms[0].get('seq', '1')}_{art.replace(':', '-')}.png",
                description_text=desc.get(art),
                provenance={"case": case, "seqs": [m.get("seq") for m in ms]},
            ).model_dump())

    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

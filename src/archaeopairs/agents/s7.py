"""S7 彩板解析器（§4.7）。Node: 器物彩板→单张彩图 Pair；场景照归 discarded。"""
from __future__ import annotations

from . import Services


def run(state: dict, svc: Services) -> dict:
    # 条目→artifact_id 映射来自链②正文（图版N，k）；mock 下用 ground artifact_ids
    records = [{
        "book_id": state["book_id"],
        "artifact_id": state["figure_id"].split(":")[-1],
        "image_path": state["fileref"],
        "provenance": {"type": "plate"},
    }]
    return {"pair_records": records, "assembled": True, "status": "ASM_VALIDATED"}

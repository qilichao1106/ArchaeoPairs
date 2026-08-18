"""S4 图像源解析器（§4.4）。Node: OCR 像素序号/比例尺(链③)。"""
from __future__ import annotations

from . import Services


def run(state: dict, svc: Services) -> dict:
    resp = svc.gateway.call(
        "ocr", svc.ocr.read, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], regions=[],
        operation="read", iteration=state.get("iteration", 0),
    )
    return {
        "seq_annotations": resp["seqs"],
        "scale_annotations": resp["scales"],
        "orientation": resp.get("orientation", "h"),
    }

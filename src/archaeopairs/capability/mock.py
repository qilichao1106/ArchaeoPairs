"""能力接口 mock 实现（P0/测试用，确定性）。

mock 依据 S1 从 XML 解析出的 ground（序号/器物号/图类）模拟 VLM/SAM/OCR
输出，使链③与链①一致、管线可收敛。生产替换为 transformers/云端实现。
"""
from __future__ import annotations

from typing import Mapping

from ..state import ScaleAnnotation, SeqAnnotation


class MockVLM:
    """VLM mock：图类判定与诊断（§4.2/§4.9）。"""

    def __init__(self, ground: Mapping[str, dict]) -> None:
        self._ground = ground

    def classify(self, *, image_ref: str, caption: str | None, trace_id: str,
                 figure_id: str = "") -> dict:
        g = self._ground.get(figure_id, {})
        return {"image_type": g.get("image_type", "line_drawing"), "confidence": 0.9}

    def diagnose(self, *, image_ref: str, context: dict, trace_id: str,
                 figure_id: str = "") -> dict:
        # 默认收敛（无缺陷）；缺陷注入由测试通过 ground 控制
        g = self._ground.get(figure_id, {})
        return {"defect_list": g.get("inject_defects", []), "confidence": 0.9}


class MockSAM:
    """SAM mock：按 ground 序号产出掩膜（掩膜三件套，§4.6）。"""

    def __init__(self, ground: Mapping[str, dict]) -> None:
        self._ground = ground

    def segment(self, *, image_ref: str, prompts: list[dict], trace_id: str,
                figure_id: str = "") -> list[dict]:
        g = self._ground.get(figure_id, {})
        masks = []
        for i, seq in enumerate(g.get("seqs", []) or ["1"]):
            masks.append({
                "mask_rle": f"rle-{figure_id}-{seq}",
                "bbox": (10 * i, 10, 100, 100),
                "area": 10000,
                "seq": str(seq),
                "note_text_region": None,
                "scale_level": 2,
            })
        return masks


class MockOCR:
    """OCR mock：按 ground 产出序号/比例尺标注（§4.4）。"""

    def __init__(self, ground: Mapping[str, dict]) -> None:
        self._ground = ground

    def read(self, *, image_ref: str, regions: list[dict], trace_id: str,
             figure_id: str = "") -> dict:
        g = self._ground.get(figure_id, {})
        seqs = [
            SeqAnnotation(text=str(s), bbox=(20 * i, 5, 20, 20)).model_dump()
            for i, s in enumerate(g.get("seqs", []))
        ]
        scales = [
            ScaleAnnotation(text="0-8厘米", bbox=(0, 200, 80, 12), seq_ref=None).model_dump()
        ]
        return {"seqs": seqs, "scales": scales, "orientation": "h"}

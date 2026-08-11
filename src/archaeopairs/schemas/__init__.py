"""JSON Schema 契约（§6.1.1 / C1）：8 核心结构 model_json_schema() 导出。"""
from __future__ import annotations

import json
from pathlib import Path

from ..state import (
    DiagnosticReport,
    FigureState,
    FusedMapping,
    MaskRecord,
    PairRecord,
    ScaleAnnotation,
    SeqAnnotation,
    TextArtifact,
)

CORE_MODELS = {
    "FigureState": FigureState,
    "TextArtifact": TextArtifact,
    "SeqAnnotation": SeqAnnotation,
    "ScaleAnnotation": ScaleAnnotation,
    "FusedMapping": FusedMapping,
    "MaskRecord": MaskRecord,
    "DiagnosticReport": DiagnosticReport,
    "PairRecord": PairRecord,
}


def all_schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in CORE_MODELS.items()}


def dump_schemas(out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, schema in all_schemas().items():
        (out / f"{name}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

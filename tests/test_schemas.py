"""JSON Schema 契约测试（§6.1.1 / C1）。"""
from __future__ import annotations

from archaeopairs.schemas import all_schemas, dump_schemas


def test_eight_schemas():
    s = all_schemas()
    assert set(s) == {"FigureState", "TextArtifact", "SeqAnnotation", "ScaleAnnotation",
                      "FusedMapping", "MaskRecord", "DiagnosticReport", "PairRecord"}
    for name, schema in s.items():
        assert "properties" in schema, name


def test_fused_mapping_multi_value_schema():
    s = all_schemas()["FusedMapping"]
    assert s["properties"]["seq_to_artifacts"]["type"] == "object"


def test_dump_schemas(tmp_path):
    dump_schemas(tmp_path)
    assert (tmp_path / "PairRecord.schema.json").exists()

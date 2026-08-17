"""JSON Schema 契约测试（Pydantic 定义与 JSON Schema（§6.1.1）/ C1）。"""
from __future__ import annotations

from archaeopairs.schemas import all_schemas, dump_schemas
from archaeopairs.state import ImageRef, PairRecord


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


def test_pair_record_candidate_images():
    pr = PairRecord(
        book_id="b",
        artifact_id="M4:1",
        image_path="primary.png",
        candidate_images=[ImageRef(path="plate.png", role="plate")],
        image_merge_mode="line_plus_plate",
    )
    assert pr.candidate_images[0].role == "plate"
    assert pr.image_merge_mode == "line_plus_plate"

"""V0.3 S7 single-artifact parser tests (lines and plates)."""
from __future__ import annotations

from archaeopairs.agents import s7, s8


def test_plate_artifact_single_from_note(services):
    st = {"image_type": "single_plate_artifact", "caption": "图版一 器物",
          "book_id": "b", "figure_id": "b:plate", "fileref": "m/p.jpg",
          "figure_note": "1. 罐（M4:1）",
          "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "CLASSIFIED_PLATE"
    item = out["single_artifacts"][0]
    assert item["artifact_id"] == "M4:1"
    assert item["role"] == "plate"
    assert item["source"] == "figure_note"


def test_single_line_from_caption(services):
    st = {"image_type": "single_line_artifact", "caption": "图2-1-5 M4出土铜鼎（M4：6）纹饰",
          "book_id": "b", "figure_id": "b:line", "fileref": "m/i.jpg",
          "figure_note": None, "text_artifacts": [], "body_paras": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "CLASSIFIED"
    item = out["single_artifacts"][0]
    assert item["artifact_id"] == "M4:6"
    assert item["role"] == "line_drawing"
    assert item["source"] == "caption"
    assert out["degraded"] is True


def test_multi_plate_archived(services):
    st = {"image_type": "multi_plate_artifact", "caption": "图版一 器物",
          "book_id": "b", "figure_id": "b:multi", "fileref": "m/p.jpg",
          "figure_note": "1. 罐（M4:1） 2. 壶（M4:2）",
          "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "EXCLUDED"
    assert out["exclude_reason"] == "discarded_archived"
    assert out["pair_records"] == []


def test_discarded_archived(services):
    st = {"image_type": "discarded", "caption": "图一 器物组合",
          "book_id": "b", "figure_id": "b:scene", "fileref": "m/s.jpg",
          "figure_note": None, "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "EXCLUDED"
    assert out["pair_records"] == []


def test_plate_no_artifact_pending(services):
    st = {"image_type": "single_plate_artifact", "caption": "图版一",
          "book_id": "b", "figure_id": "b:empty", "fileref": "m/p.jpg",
          "figure_note": None, "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "PENDING_REVIEW"
    assert out["exclude_reason"] == "single_artifact_id_missing"


def test_s8_assembles_single_whole_image(services):
    st = {"image_type": "single_plate_artifact", "caption": "图版一 器物",
          "book_id": "b", "figure_id": "b:plate", "fileref": "m/p.jpg",
          "figure_note": "1. 罐（M4:1）",
          "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    final = s8.run({**st, **out}, services)
    assert final["status"] == "ASM_VALIDATED"
    record = final["pair_records"][0]
    assert record["artifact_id"] == "M4:1"
    assert record["image_path"] == "图版一_01_M4-1.png"
    assert record["image_merge_mode"] == "plate_only"
    assert record["provenance"]["single"] is True

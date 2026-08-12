"""S7 plate parser tests: not relying on mock ground, mapping from note/text."""
from __future__ import annotations

from archaeopairs.agents import s7


def test_plate_artifact_from_note(services):
    st = {"image_type": "plate_artifact", "caption": "图版一 器物",
          "book_id": "b", "figure_id": "b:plate", "fileref": "m/p.jpg",
          "figure_note": "1. 罐（M4:1） 2. 壶（M4:2）",
          "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    arts = {r["artifact_id"] for r in out["pair_records"]}
    assert arts == {"M4:1", "M4:2"}
    assert out["status"] == "ASM_VALIDATED"


def test_plate_scene_excluded(services):
    st = {"image_type": "plate_scene", "caption": "图版一 墓葬场景",
          "book_id": "b", "figure_id": "b:scene", "fileref": "m/s.jpg",
          "figure_note": None, "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "EXCLUDED"
    assert out["pair_records"] == []


def test_plate_no_artifact_pending(services):
    st = {"image_type": "plate_artifact", "caption": "图版一",
          "book_id": "b", "figure_id": "b:empty", "fileref": "m/p.jpg",
          "figure_note": None, "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["status"] == "PENDING_REVIEW"

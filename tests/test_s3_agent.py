from __future__ import annotations

from archaeopairs.agents import s3


def test_s3_filters_by_figure_and_confirms_low_confidence(services):
    state = {
        "book_id": "b",
        "figure_id": "b:f1",
        "fileref": "media/image1.jpg",
        "caption": "图一 出土器物",
        "figure_note": "",
        "body_paras": [
            {"id": "p1", "text": "图一 M4:1 陶豆。"},
            {"id": "p2", "text": "图一 1件。口径10厘米。"},
        ],
        "iteration": 0,
        "trace_id": "t-s3",
    }
    out = s3.run(state, services)
    assert [t["artifact_id"] for t in out["text_artifacts"]] == ["M4:1", "M4:1"]
    assert "llm_confirmed" in out["text_artifacts"][1]["markers"]

"""图题器物号兜底测试（对齐《技术方案 V0.3》图题器物号兜底识别（§2.2.5））。

覆盖：图题纯扫描（图号不误判为序号/重复出现去重/圈号保留/紧贴序号剥离/部件号）、
S3 图题兜底抽取与正文筛选、S5 仲裁（单号 rule_b / 多号 seq_missing+E005 / 链①优先 /
弱链①置信折扣）、S7 彩板图题兜底、S10 降级不误挂起、合成与真实报告端到端。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from archaeopairs.agents import Services, s3, s5, s7, s8, s10
from archaeopairs.capability import MockOCR, MockSAM, MockVLM
from archaeopairs.cli import _book_has_artifact
from archaeopairs.config import load_flags, load_thresholds
from archaeopairs.gateway import Gateway
from archaeopairs.orchestration import build_graph
from archaeopairs.parsers import s1_xml, s3_note

EXAMPLES = Path(__file__).resolve().parents[1] / "books"


# ---------- extract_caption_artifacts 纯扫描 ----------


def test_caption_single_artifact_hongdong_shape():
    # 洪洞南秦实测形态：章序式图号不得误判，全角冒号归一
    arts = s3_note.extract_caption_artifacts("图2-1-5 M4出土铜鼎（M4：6）纹饰")
    assert arts == ["M4:6"]


def test_caption_no_artifact():
    # 墓葬号无冒号不是器物号；纯描述图题无号
    assert s3_note.extract_caption_artifacts("图七 M1、M2出土器物") == []
    assert s3_note.extract_caption_artifacts("图一 出土器物") == []
    assert s3_note.extract_caption_artifacts(None) == []
    assert s3_note.extract_caption_artifacts("") == []


def test_caption_dup_deduped():
    # 后蜀赵廷隐实测形态：同器双视图在图题中两次出现 → 去重
    cap = "图版七二 B型雷公俑（M1：54）左侧、图版七三 B型雷公俑（M1：54）右侧"
    assert s3_note.extract_caption_artifacts(cap) == ["M1:54"]


def test_caption_multi_artifacts():
    # 后屯下册实测形态：多器物号按出现顺序保留
    cap = "图五 珠饰M723：5（BJFZX-9）、M723：12（BJFZX-11）和M743：4（BJFZX-12）的拉曼图谱"
    assert s3_note.extract_caption_artifacts(cap) == ["M723:5", "M723:12", "M743:4"]


def test_caption_circled_preserved():
    assert s3_note.extract_caption_artifacts("图一 陶罐（H83①：35）") == ["H83①:35"]


def test_caption_glued_seq_stripped():
    # 紧贴序号形态：序号 1 粘在器物号前 → 剥离
    assert s3_note.extract_caption_artifacts("图一二五 M16出土银簪1.00FBG1:2") == ["00FBG1:2"]


def test_caption_component_id():
    assert s3_note.extract_caption_artifacts("图三 Zhb2 倚柱残件") == ["Zhb2"]


# ---------- S3：图题兜底抽取与正文筛选 ----------


def test_s3_caption_fallback_selects_body(services):
    state = {
        "book_id": "b", "figure_id": "b:f-cap", "fileref": "media/image1.jpg",
        "caption": "图2-1-5 M4出土铜鼎（M4：6）纹饰",
        "figure_note": None,
        "body_paras": [
            {"id": "p1", "text": "M4：6，铜鼎。口径20厘米。"},
            {"id": "p2", "text": "M7：1，陶罐。口径12厘米。"},  # 无关器物不取
        ],
        "iteration": 0, "trace_id": "t-cap",
    }
    out = s3.run(state, services)
    assert out["caption_artifacts"] == ["M4:6"]
    assert [t["artifact_id"] for t in out["text_artifacts"]] == ["M4:6"]


def test_s3_note_wins_over_caption(services):
    # 链①有器物号时不启用图题兜底（链①为 Pair 键唯一权威源）
    state = {
        "book_id": "b", "figure_id": "b:f-note", "fileref": "media/image2.jpg",
        "caption": "图一 出土器物（M9：9）",
        "figure_note": "1. 陶豆（M4：1）",
        "body_paras": [], "iteration": 0, "trace_id": "t-note",
    }
    out = s3.run(state, services)
    assert out["caption_artifacts"] == []


# ---------- S5：图题兜底仲裁 ----------


def test_s5_caption_single_art_rule_b(services):
    st = {"note_items": [], "caption_artifacts": ["M4:6"], "figure_note": None,
          "seq_annotations": [], "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_b"
    assert out["degraded"] is True
    assert out["alarms"] == []
    assert out["fused"]["caption_artifacts"] == ["M4:6"]
    assert out["fused"]["seq_to_artifacts"] == {}
    assert out["confidence"] == pytest.approx(0.85 * 0.8)  # 弱链① ×0.8


def test_s5_caption_single_art_with_chains_conf(services):
    st = {"note_items": [], "caption_artifacts": ["M4:6"], "figure_note": None,
          "seq_annotations": [{"text": "1", "bbox": (0, 0, 1, 1)}],
          "text_artifacts": [{"artifact_id": "M4:6"}]}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_b"
    assert out["confidence"] == pytest.approx(0.95 * 0.8)


def test_s5_caption_multi_arts_pending(services):
    st = {"note_items": [], "caption_artifacts": ["M16:2", "M16:1"], "figure_note": None,
          "seq_annotations": [], "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "seq_missing"
    assert "E005" in out["alarms"]
    assert any(c.startswith("caption_multi_artifacts") for c in out["fused"]["conflicts"])


def test_s5_note_wins_over_caption(services):
    st = {"note_items": [{"seq": "1", "seq_list": [1], "name": None, "artifact_ids": ["M4:1"]}],
          "caption_artifacts": ["M9:9"], "figure_note": "1. 陶豆（M4：1）",
          "seq_annotations": [{"text": "1", "bbox": (0, 0, 1, 1)}], "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "rule_a"
    assert out["fused"]["caption_artifacts"] == []
    assert out["confidence"] == pytest.approx(0.85)  # 链①+链③，不受图题折扣


# ---------- S7：彩板图题兜底 ----------


def test_s7_plate_caption_fallback(services):
    st = {"image_type": "plate_artifact", "book_id": "b", "figure_id": "b:plate-cap",
          "fileref": "m/p.jpg", "figure_note": None, "text_artifacts": [], "trace_id": "t",
          "caption": "图版七二 B型雷公俑（M1：54）左侧、图版七三 B型雷公俑（M1：54）右侧"}
    out = s7.run(st, services)
    assert out["status"] == "CLASSIFIED_PLATE"
    assert [i["artifact_id"] for i in out["single_artifacts"]] == ["M1:54"]
    assert out["single_artifacts"][0]["source"] == "caption"
    final = s8.run({**st, **out}, services)
    assert final["status"] == "ASM_VALIDATED"
    assert final["pair_records"][0]["image_path"] == "图版七二_01_M1-54.png"


def test_s10_degraded_caption_not_pending(services):
    st = {"figure_id": "b:f-cap", "case_type": "rule_b", "degraded": True, "alarms": [],
          "defect_history": [0], "iteration": 0,
          "fused": {"seq_to_artifacts": {}, "caption_artifacts": ["M4:6"]}}
    out = s10.run(st, services)
    assert out["status"] == "OUTPUT"


def test_s10_degraded_no_mapping_pending(services):
    st = {"figure_id": "b:f-none", "case_type": "seq_missing", "degraded": True, "alarms": [],
          "defect_history": [0], "iteration": 0,
          "fused": {"seq_to_artifacts": {}, "caption_artifacts": []}}
    out = s10.run(st, services)
    assert out["status"] == "PENDING_REVIEW"


# ---------- §2.5 无器物号检测：图题信号 ----------


def test_book_has_artifact_caption_signal():
    fig = SimpleNamespace(caption="图2-1-5 M4出土铜鼎（M4：6）纹饰", figure_note=None)
    assert _book_has_artifact([], [fig]) is True
    fig_none = SimpleNamespace(caption="图一 出土器物", figure_note=None)
    assert _book_has_artifact([], [fig_none]) is False


# ---------- 端到端：合成 XML（无图注 + 图题含器物号） ----------

CAPTION_ONLY_XML = """<book>
<section>
<figure><mediaobject><imageobject><imagedata fileref="media/image1.jpg"/></imageobject></mediaobject>
<caption role="figure-title"><para role="figure-title">图2-1-5 M4出土铜鼎（M4：6）纹饰</para></caption></figure>
</section>
</book>"""


def _services_from(ground: dict) -> Services:
    th = load_thresholds()
    fl = load_flags()
    return Services(vlm=MockVLM(ground), sam=MockSAM(ground), ocr=MockOCR(ground),
                    gateway=Gateway(),
                    thresholds=th, flags=fl)


def test_graph_caption_fallback_end_to_end(tmp_path: Path):
    p = tmp_path / "data.xml"
    p.write_text(CAPTION_ONLY_XML, encoding="utf-8")
    figures, ground, violations = s1_xml.parse_report(p, "cap")
    assert violations == []
    fig = figures[0]
    # S1 ground 同口径：图注无号 → 图题兜底
    assert ground[fig.figure_id]["artifact_ids"] == ["M4:6"]

    svc = _services_from(ground)
    init = {"book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
            "caption": fig.caption, "figure_note": fig.figure_note,
            "book_has_artifact": True, "body_paras": [],
            "iteration": 0, "defect_history": [], "assembled": False,
            "trace_id": "t-cap-e2e", "flags": load_flags().model_dump(), "status": "INIT"}
    db = tmp_path / "ckpt.sqlite3"
    with SqliteSaver.from_conn_string(str(db)) as ckpt:
        app = build_graph(svc, checkpointer=ckpt)
        result = app.invoke(init, config={"configurable": {"thread_id": "t:cap"}})
    assert result["status"] == "OUTPUT"
    assert result["case_type"] == "single_line"
    assert result["degraded"] is True
    records = result["pair_records"]
    assert len(records) == 1
    assert records[0]["artifact_id"] == "M4:6"
    assert records[0]["image_path"] == "图2-1-5_01_M4-6.png"
    assert records[0]["provenance"]["art_source"] == "caption"


# ---------- 端到端：洪洞南秦真实形态回归 ----------


@pytest.mark.skipif(not (EXAMPLES / "洪洞南秦墓地二〇一六年度发掘报告").exists(),
                    reason="books/洪洞南秦 不存在")
def test_graph_real_hongdong_caption_fallback(tmp_path: Path):
    xml = EXAMPLES / "洪洞南秦墓地二〇一六年度发掘报告" / "data.xml"
    figures, ground, _ = s1_xml.parse_report(xml, "hongdong")
    fig = next(f for f in figures
               if not f.figure_note and s3_note.extract_caption_artifacts(f.caption))
    expect = s3_note.extract_caption_artifacts(fig.caption)
    assert ground[fig.figure_id]["artifact_ids"] == expect

    svc = _services_from(ground)
    init = {"book_id": fig.book_id, "figure_id": fig.figure_id, "fileref": fig.fileref,
            "caption": fig.caption, "figure_note": fig.figure_note,
            "book_has_artifact": True, "body_paras": [],
            "iteration": 0, "defect_history": [], "assembled": False,
            "trace_id": "t-hd", "flags": load_flags().model_dump(), "status": "INIT"}
    db = tmp_path / "ckpt.sqlite3"
    with SqliteSaver.from_conn_string(str(db)) as ckpt:
        app = build_graph(svc, checkpointer=ckpt)
        result = app.invoke(init, config={"configurable": {"thread_id": "t:hd"}})
    if len(expect) == 1:
        assert result["status"] == "OUTPUT"
        records = result["pair_records"]
        assert len(records) == 1 and records[0]["artifact_id"] == expect[0]
        assert records[0]["provenance"]["art_source"] == "caption"
    else:  # 多器物号图题 → 人工复核
        assert result["status"] == "PENDING_REVIEW"
        assert "E005" in result["alarms"]

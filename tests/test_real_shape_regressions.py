"""真实数据形态回归测试（books 中间态反例契约锁，对应代码评审 P0/P1 缺陷）。

覆盖：全角冒号/全角波浪线/圈号原文保留/无空格紧贴/公式残迹/同图号分组/
图注前置/相邻图题恢复/位置对应配对（禁笛卡尔）/图号 O 归一/确定性 event_id。
"""
from __future__ import annotations

from pathlib import Path

from archaeopairs import naming
from archaeopairs.agents import s3, s5, s7, s8, s10
from archaeopairs.parsers import s1_xml, s3_note

# ---------- 归一化与图注解析（F3/F4/公式残迹/无空格） ----------


def test_fullwidth_colon_normalized():
    items = s3_note.parse_note("1. 陶罐（M369∶4）")
    assert items[0].artifact_ids == ["M369:4"]


def test_circled_artifact_preserved_original():
    # 圈号归一仅用于匹配；artifact_id 回映原文保留 ①
    items = s3_note.parse_note("1. 陶罐（H83①:35）")
    assert items[0].artifact_ids == ["H83①:35"]


def test_circled_suffix_artifact_preserved():
    items = s3_note.parse_note("1. 陶拍（C11T112③:27）")
    assert items[0].artifact_ids == ["C11T112③:27"]


def test_fullwidth_range_normalized():
    items = s3_note.parse_note("1～4. 豆（M3:4、M3:2、M3:3、M3:1） 5. 壶（M3:5）")
    assert items[0].seq_list == [1, 2, 3, 4]
    assert "~" in items[0].seq
    assert items[1].seq_list == [5]


def test_no_space_artifact():
    # "1.00FBG1:2"：序号 1 紧贴器物号 00FBG1:2
    items = s3_note.parse_note("1.00FBG1:2 2.00FBG1:1")
    assert items[0].seq_list == [1] and items[0].artifact_ids == ["00FBG1:2"]
    assert items[1].seq_list == [2] and items[1].artifact_ids == ["00FBG1:1"]


def test_latex_math_residue():
    items = s3_note.parse_note("$1\\sim 4$ 陶豆 5.陶壶")
    assert items[0].seq_list == [1, 2, 3, 4]
    assert items[1].seq_list == [5]


def test_noise_still_skipped():
    assert s3_note.parse_note("0 8厘米") == []


# ---------- S1 figure↔figure-note 关联（P0-1） ----------


def test_multi_note_paras_joined(tmp_path: Path):
    xml = ("<book><section>"
           "<figure><mediaobject><imageobject><imagedata fileref='m/i.jpg'/></imageobject></mediaobject>"
           "<caption role='figure-title'><para role='figure-title'>图一 器物组合</para></caption></figure>"
           "<para role='figure-note'>1. 陶鼎（M4:5）</para>"
           "<para role='figure-note'>2. 陶盒（M4:7）</para>"
           "</section></book>")
    p = tmp_path / "data.xml"
    p.write_text(xml, encoding="utf-8")
    figures, ground, violations = s1_xml.parse_report(p, "b")
    assert violations == []
    assert figures[0].figure_note is not None and "陶盒" in figures[0].figure_note
    assert ground[figures[0].figure_id]["seqs"] == ["1", "2"]


def test_note_precedes_figure(tmp_path: Path):
    xml = ("<book><section>"
           "<para role='figure-note'>6. 陶三足砚（M3:4）</para>"
           "<figure><mediaobject><imageobject><imagedata fileref='m/i.jpg'/></imageobject></mediaobject>"
           "<caption role='figure-title'><para role='figure-title'>图版六三</para></caption></figure>"
           "</section></book>")
    p = tmp_path / "data.xml"
    p.write_text(xml, encoding="utf-8")
    figures, ground, _ = s1_xml.parse_report(p, "b")
    assert "陶三足砚" in (figures[0].figure_note or "")
    assert ground[figures[0].figure_id]["artifact_ids"] == ["M3:4"]


def test_same_caption_group_note_to_largest(tmp_path: Path):
    # 同图号两张图（组合图 494x534 + 比例尺条图 93x27）：图注归组合图
    xml = ("<book><section>"
           "<figure><mediaobject><imageobject>"
           "<imagedata fileref='m/big.jpg' contentwidth='494' contentdepth='534'/>"
           "</imageobject></mediaobject>"
           "<caption role='figure-title'><para role='figure-title'>图四 器物组合</para></caption></figure>"
           "<figure><mediaobject><imageobject>"
           "<imagedata fileref='m/strip.jpg' contentwidth='93' contentdepth='27'/>"
           "</imageobject></mediaobject>"
           "<caption role='figure-title'><para role='figure-title'>图四 器物组合</para></caption></figure>"
           "<para role='figure-note'>1. 陶鼎（M11:5）</para>"
           "</section></book>")
    p = tmp_path / "data.xml"
    p.write_text(xml, encoding="utf-8")
    figures, ground, _ = s1_xml.parse_report(p, "b")
    big = next(f for f in figures if f.fileref == "m/big.jpg")
    strip = next(f for f in figures if f.fileref == "m/strip.jpg")
    assert big.figure_note == "1. 陶鼎（M11:5）"
    assert strip.figure_note is None
    assert ground[big.figure_id]["artifact_ids"] == ["M11:5"]


def test_adjacent_title_recovers_caption(tmp_path: Path):
    # 无 caption 的 figure 从前置 para role="figure-title" 恢复图题
    xml = ("<book><section>"
           "<para role='figure-note'>1. 瓷碗（M3:2）</para>"
           "<para role='figure-title'>图版六三</para>"
           "<figure><mediaobject><imageobject><imagedata fileref='m/p.jpg'/></imageobject></mediaobject></figure>"
           "</section></book>")
    p = tmp_path / "data.xml"
    p.write_text(xml, encoding="utf-8")
    figures, ground, violations = s1_xml.parse_report(p, "b")
    assert violations == []
    assert figures[0].caption == "图版六三"
    assert ground[figures[0].figure_id]["image_type"] == "single_plate_artifact"


def test_violation_records_fileref_and_reason(tmp_path: Path):
    xml = ("<book><section>"
           "<figure><mediaobject><imageobject><imagedata fileref='m/untitled.jpg'/></imageobject>"
           "</mediaobject></figure>"
           "</section></book>")
    p = tmp_path / "data.xml"
    p.write_text(xml, encoding="utf-8")
    figures, _, violations = s1_xml.parse_report(p, "b")
    assert len(figures) == 1 and figures[0].caption is None  # 保留记录，由 S1 节点排除
    assert len(violations) == 1
    assert "untitled.jpg" in violations[0] and "caption_missing" in violations[0]


def test_contract_violation_figure_kept(tmp_path: Path):
    bad = "<book><figure><mediaobject><imageobject><imagedata fileref='m/i.jpg'/>" \
          "</imageobject></mediaobject><caption><para>无role</para></caption></figure></book>"
    p = tmp_path / "data.xml"
    p.write_text(bad, encoding="utf-8")
    figures, _, violations = s1_xml.parse_report(p, "bad")
    assert len(figures) == 1
    assert figures[0].caption is None
    assert len(violations) == 1 and "caption_missing" in violations[0]


# ---------- S5 位置对应配对（F2/F3） ----------


def _ni(seq, seq_list, arts):
    return {"seq": seq, "seq_list": seq_list, "name": None, "artifact_ids": arts}


def _sa(*seqs):
    return [{"text": str(s), "bbox": (0, 0, 1, 1)} for s in seqs]


def test_split_same_seq_positional_zip(services):
    # "4、6. 陶魁（:5、:10）" → 4→:5、6→:10，2 条而非 4 条
    st = {"note_items": [_ni("4、6", [4, 6], ["H1:5", "H1:10"])],
          "seq_annotations": _sa(4, 6), "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "split_same_seq"
    assert out["fused"]["seq_to_artifacts"] == {"4": ["H1:5"], "6": ["H1:10"]}
    assert out["fused"]["conflicts"] == []


def test_split_same_seq_single_seq_multi_art(services):
    # 单 seq 多 artifact：同号多器，共享掩膜拆 Pair
    st = {"note_items": [_ni("2", [2], ["H1:6", "H1:3"])],
          "seq_annotations": _sa(2), "text_artifacts": []}
    out = s5.run(st, services)
    assert out["fused"]["seq_to_artifacts"] == {"2": ["H1:6", "H1:3"]}


def test_fullwidth_range_case_type(services):
    st = {"note_items": [_ni("1~4", [1, 2, 3, 4], ["M3:4", "M3:2", "M3:3", "M3:1"])],
          "seq_annotations": _sa(1, 2, 3, 4), "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "range_split"
    assert out["fused"]["seq_to_artifacts"]["3"] == ["M3:3"]
    assert out["fused"]["seq_to_artifacts"]["1"] == ["M3:4"]


def test_rule_a_group_positional_zip(services):
    # "1、2. 陶豆（M4:2、M4:1）" → 1→M4:2、2→M4:1（不展开）
    st = {"note_items": [_ni("1、2", [1, 2], ["M4:2", "M4:1"]),
                         _ni("3", [3], ["M4:3"])],
          "seq_annotations": _sa(1, 2, 3), "text_artifacts": []}
    out = s5.run(st, services)
    assert out["case_type"] == "split_same_seq"
    assert out["fused"]["seq_to_artifacts"] == {"1": ["M4:2"], "2": ["M4:1"], "3": ["M4:3"]}


def test_mismatched_counts_record_conflict(services):
    # 数量不一致且无法唯一对应 → 冲突登记，不猜测
    st = {"note_items": [_ni("2、9", [2, 9], ["H1:6", "H1:3", "H1:8"])],
          "seq_annotations": _sa(2, 9), "text_artifacts": []}
    out = s5.run(st, services)
    assert any("seq_art_mismatch" in c for c in out["fused"]["conflicts"])


# ---------- S3 正文筛选（F1 全角冒号失配） ----------


def test_body_filter_fullwidth_colon(services):
    state = {
        "book_id": "b", "figure_id": "b:f1", "fileref": "media/image1.jpg",
        "caption": "图四 器物组合",
        "figure_note": "1. 陶鼎（2004CWWM11：5） 2. 陶盒（2004CWWM11：7）",
        "body_paras": [
            {"id": "p1", "text": "鼎 1件。2004CWWM11：5，子母口，上腹壁稍直，圜底。口径12.6厘米。"},
            {"id": "p2", "text": "与本报告无关的段落。"},
        ],
        "iteration": 0, "trace_id": "t-s3",
    }
    out = s3.run(state, services)
    arts = [t["artifact_id"] for t in out["text_artifacts"]]
    assert "2004CWWM11:5" in arts
    assert all("无关" not in t["text"] for t in out["text_artifacts"])


# ---------- 图号归一（P1-5） ----------


def test_fig_number_o_normalized():
    assert naming.extract_fig_number("图二六O 地层出土帽钉") == "图二六〇"
    assert naming.extract_fig_number("图 三一 平剖面图") == "图三一"
    assert naming.extract_fig_number("图2-1-16b M4出土铜舟") == "图2-1-16b"


def test_fig_number_body_ref_canonical():
    canon = naming.canonical_fig_text("（图二六O；图版六八，3）")
    assert "图二六〇" in canon


def test_single_path_name_uses_01_placeholder():
    # V0.5.1 §7.2：单器物路径无图片内序号 → 序号段固定占位 01
    assert naming.build_image_name("图2-1-5", None, "M4:6") == "图2-1-5_01_M4-6.png"
    assert naming.build_image_name("图版七二", None, "M1:54") == "图版七二_01_M1-54.png"


def test_multi_path_name_keeps_seq():
    assert naming.build_image_name("图四", "4", "H1:5") == "图四_4_H1-5.png"


# ---------- S7 彩板（F8/F10） ----------


def test_plate_o_number(services):
    st = {"image_type": "single_plate_artifact", "caption": "图版三O",
          "book_id": "b", "figure_id": "b:plate", "fileref": "m/p.jpg",
          "figure_note": "1. 罐（M4:1）", "text_artifacts": [], "trace_id": "t"}
    out = s7.run(st, services)
    assert out["single_artifacts"][0]["artifact_id"] == "M4:1"
    final = s8.run({**st, **out}, services)
    assert final["pair_records"][0]["image_path"].startswith("图版三〇_")
    assert "description_text" in final["pair_records"][0]  # PairRecord schema 一致


def test_plate_rubbing_no(services):
    assert s7.plate_no_of("拓片三七 石椁内西壁线刻") == "拓片三七"


# ---------- S10 确定性 event_id（F9） ----------


def test_event_id_deterministic(services):
    st1 = {"figure_id": "b:image9", "alarms": ["E001", "E002"], "exclude_reason": None}
    st2 = {"figure_id": "b:image9", "alarms": ["E002", "E001"], "exclude_reason": None}
    e1 = s10.event_id_of(st1)
    e2 = s10.event_id_of(st2)
    assert e1 == e2  # 报警集合顺序无关
    assert s10.event_id_of({"figure_id": "b:image9", "alarms": ["E001"], "exclude_reason": None}) != e1


def test_review_task_no_duplicate_for_same_event(services, base_state):
    from archaeopairs.integrations import MockReviewBridge

    services.review_bridge = MockReviewBridge()
    st = dict(base_state)
    st["alarms"] = ["E001"]
    out1 = s10.run(st, services)
    out2 = s10.run(st, services)
    assert out1["review_events"][0]["event_id"] == out2["review_events"][0]["event_id"]
    assert len([t for t in services.review_bridge.tasks.values() if t["status"] == "OPEN"]) == 1

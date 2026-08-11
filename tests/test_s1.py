"""S1 报告索引器单元测试（§4.1，确定性，覆盖率目标 ≥80%）。"""
from __future__ import annotations

from pathlib import Path

from archaeopairs.parsers import s1_xml


def test_parse_figures_and_note(synth_book):
    figures, ground, violations = synth_book
    assert len(figures) == 1
    assert violations == []
    fig = figures[0]
    assert fig.caption == "图一 出土器物"
    assert fig.figure_note and "陶豆" in fig.figure_note
    g = ground[fig.figure_id]
    assert g["seqs"] == ["1", "2"]
    assert g["artifact_ids"] == ["M4:1", "M4:2"]
    assert g["image_type"] == "line_drawing"


def test_contract_violation(tmp_path: Path):
    bad = "<book><figure><mediaobject><imageobject><imagedata fileref='m/i.jpg'/></imageobject></mediaobject><caption><para>无role</para></caption></figure></book>"  # noqa: E501
    p = tmp_path / "data.xml"
    p.write_text(bad, encoding="utf-8")
    figures, _, violations = s1_xml.parse_report(p, "bad")
    assert figures == []
    assert len(violations) == 1  # E102 违约清单


def test_plate_classification(tmp_path: Path):
    xml = "<book><figure><mediaobject><imageobject><imagedata fileref='m/p.jpg'/></imageobject></mediaobject><caption role='figure-title'><para role='figure-title'>图版一 器物</para></caption></figure></book>"  # noqa: E501
    p = tmp_path / "data.xml"
    p.write_text(xml, encoding="utf-8")
    _, ground, _ = s1_xml.parse_report(p, "plate")
    assert list(ground.values())[0]["image_type"] == "plate_artifact"

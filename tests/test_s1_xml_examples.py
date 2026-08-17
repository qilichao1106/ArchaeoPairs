"""针对 s1_xml 解析器在 examples 真实 XML + media 上的单元验证。

以「洪洞南秦墓地二〇一六年度发掘报告」的真实 data.xml 与 media/ 为样本：
  * parse_report：验证 figure 提取、ground 结构、fileref 命中真实 media 实体、
    violations 契约格式（figure_id|fileref|原因）；
  * parse_body：验证链②正文语料剔除 figure-note/figure-title/table-title/qr-caption。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from archaeopairs.parsers import s1_xml

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REPORT = EXAMPLES / "洪洞南秦墓地二〇一六年度发掘报告"
XML = REPORT / "data.xml"
MEDIA = REPORT / "media"


def _require_sample() -> Path:
    if not XML.exists():
        pytest.skip("examples 真实样本缺失")
    return XML


@pytest.fixture(scope="module")
def report_parse():
    xml = _require_sample()
    fig, ground, violations = s1_xml.parse_report(xml, "hongtong-nanqin")
    body = s1_xml.parse_body(xml)
    return fig, ground, violations, body


# ---------- parse_report 真实样本 ----------


def test_reports_figures_and_ground(report_parse):
    fig, ground, _, _ = report_parse
    assert len(fig) > 0, "真实报告应解析出 figure"
    assert len(ground) == len(fig), "ground 与 figures 数量应一致"
    assert all(f.figure_id in ground for f in fig), "ground 键应覆盖全部 figure_id"


def test_figure_state_fields(report_parse):
    fig, _, _, _ = report_parse
    for f in fig:
        assert f.figure_id.startswith("hongtong-nanqin:")
        assert f.status == "INIT"
        assert f.book_id == "hongtong-nanqin"
        assert isinstance(f.caption, str | None)


def test_fileref_hits_real_media(report_parse):
    """upstream 输入契约：fileref 应命中 media/ 下真实实体文件。"""
    fig, _, _, _ = report_parse
    assert len(fig) >= 100, f"洪洞南秦为全彩/线图大型报告，figure 数应较多, got {len(fig)}"
    missing = [f.fileref for f in fig if f.fileref and (MEDIA / Path(f.fileref).name).exists() is False]
    assert not missing, f"以下 fileref 未命中 media 实体: {missing[:10]}"
    assert all(f.fileref for f in fig), "figure 应都有 fileref"


def test_ground_schema(report_parse):
    fig, ground, _, _ = report_parse
    valid_types = {"single_line", "multi_line", "line_drawing",
                       "plate_artifact", "plate_scene", "multi_plate", "discarded"}
    for f in fig:
        g = ground[f.figure_id]
        assert set(g) == {"seqs", "artifact_ids", "image_type"}
        assert g["image_type"] in valid_types
        assert isinstance(g["seqs"], list)
        assert isinstance(g["artifact_ids"], list)


def test_violation_contract_format(report_parse):
    """违约清单格式：figure_id|fileref|原因；原因限已知两类。"""
    _, _, violations, _ = report_parse
    for v in violations:
        parts = v.split("|")
        assert len(parts) == 3, f"violations 格式错误: {v!r}"
        assert parts[2] in {"caption_missing", "media_missing"}, f"未知原因: {v!r}"


def test_figure_note_present_for_artifact_figs(report_parse):
    """含图注的真实图应解析出 figure_note 与 ground 器物信息。"""
    fig, ground, _, _ = report_parse
    noted = [f for f in fig if f.figure_note]
    assert len(noted) > 0, "真实报告应存在带 figure-note 的图"
    example = next(f for f in fig if f.figure_note)
    g = ground[example.figure_id]
    # 抽取出的 seq/artifact 至少其一非空
    assert g["seqs"] or g["artifact_ids"], f"figure_note 非空但 ground 空: {example.figure_note!r}"


# ---------- parse_body 真实样本 ----------


def test_body_produced(report_parse):
    _, _, _, body = report_parse
    assert len(body) > 0, "正文语料应产出段落"
    assert all(p["text"].strip() for p in body)


def test_body_excludes_roles(report_parse):
    """链②正文不得含 figure-note 整段文本（figure-title/table-title/qr-caption 亦被跳过）。

    注：不按 caption 作子串匹配——简短图题（如「捉手」「图版三」）与正文词汇
    重叠属正常现象，不应误判为污染。
    """
    _, _, _, body = report_parse
    joined = "\n".join(p["text"] for p in body)

    # 抽样的真实 figure-note 整段文本不得进入正文
    for v in ("1. M4 : 14-1", "1. 金圆形饰（M4：15）", "1、24、25、73、74、88、133、134.铜戈"):
        assert v not in joined, f"figure-note 漏入正文语料: {v!r}"

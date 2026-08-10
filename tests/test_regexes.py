# -*- coding: utf-8 -*-
"""regexes 单测：覆盖器物号/图号归一化与图注四形态（附录C B1–B3 修复的回归门禁）。

运行：python -m pytest tests/test_regexes.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from archaeopairs.regexes import (normalize_artifact_id, normalize_figure_no,
                                  parse_figure_note, caption_mode, ARTIFACT_ID_NORM_RE)


# ---- B1：数字开头器物号（基准样本主导形态，1167 处）
def test_artifact_id_digit_led():
    assert normalize_artifact_id("00FBG1:2") == ("00FBG1-2", "00FBG1:2")
    assert normalize_artifact_id("00FBH1:6")[0] == "00FBH1-6"


def test_artifact_id_fullwidth_colon():
    assert normalize_artifact_id("00FBF1：1")[0] == "00FBF1-1"


def test_artifact_id_letter_led():
    assert normalize_artifact_id("M4:2")[0] == "M4-2"


# ---- B2：子编号保留（多段连字符）
def test_artifact_id_sub_number():
    norm, _ = normalize_artifact_id("00FBH1:5-2")
    assert norm == "00FBH1-5-2"
    assert ARTIFACT_ID_NORM_RE.match(norm)


# ---- B3：圈号归一（original 保留）
def test_artifact_id_circle():
    norm, original = normalize_artifact_id("05FBCQ1②:8")
    assert norm == "05FBCQ12-8"
    assert original == "05FBCQ1②:8"
    assert ARTIFACT_ID_NORM_RE.match(norm)


# ---- 图号归一
def test_figure_no_variants():
    assert normalize_figure_no("图2-1-16 M4出土铜鼎")[0] == "图2-1-16"
    assert normalize_figure_no("图一六 白帝山出土遗物")[0] == "图16"
    assert normalize_figure_no("图一〇〇 器物")[0] == "图100"
    assert normalize_figure_no("图三三二 器物")[0] == "图332"
    assert normalize_figure_no("图七a M1、M2出土器物")[0] == "图7a"
    assert normalize_figure_no("图2-1-16b 器物")[0] == "图2-1-16b"


# ---- 图题先验分流
def test_caption_mode():
    assert caption_mode("图一 奉节县区位图") == "non"
    assert caption_mode("图16 白帝山遗址出土遗物") == "artifact"
    assert caption_mode("M4出土器物平面图") == "non"
    assert caption_mode("某某图") == "uncertain"


# ---- 图注四形态
def test_note_compact():
    r = parse_figure_note("1.00FBG1:2 2.00FBG1:1")
    assert r.entries[0].seqs == ["1"] and r.entries[0].ids == ["00FBG1-2"]
    assert r.entries[1].ids == ["00FBG1-1"]
    assert not r.residuals


def test_note_fullwidth():
    r = parse_figure_note("1.铁片（00FBF1：1）")
    assert r.entries[0].ids == ["00FBF1-1"]
    assert r.entries[0].name == "铁片"


def test_note_range():
    r = parse_figure_note("2～5.筒瓦(03FBSL1：1、03FBSL1：2、03FBSL1：3、03FBSL1：4)")
    e = r.entries[0]
    assert e.form == "range"
    assert e.seqs == ["2", "3", "4", "5"]
    assert len(e.ids) == 4


def test_note_same_id_two():
    r = parse_figure_note("2、9.铁器（00FBH1：6、00FBH1：3）")
    e = r.entries[0]
    assert e.form == "same_id"
    assert e.seqs == ["2", "9"]
    assert e.ids == ["00FBH1-6", "00FBH1-3"]


def test_note_same_id_three():
    """B3：三个及以上序号"""
    r = parse_figure_note("2、9、11.铁器（00FBH1：6）")
    assert r.entries[0].seqs == ["2", "9", "11"]


def test_note_residual():
    r = parse_figure_note("器物残件若干")
    assert r.residuals and not r.entries


def test_note_scale_extract():
    r = parse_figure_note("1.瓷碗(M4:2) 0-6厘米")
    assert "0-6厘米" in r.scales

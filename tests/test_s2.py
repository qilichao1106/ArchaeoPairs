"""V0.4.1 S2 图类判定测试：XML 器物号 = 主信号、关键词定线/彩家族、五分类命名。"""
from __future__ import annotations

from archaeopairs.parsers.keywords import decide_image_class


def test_no_artifact_discarded():
    assert decide_image_class("图一 出土器物", None) == "discarded"
    assert decide_image_class("图版三 墓葬全景", None) == "discarded"  # plate_scene 并入


def test_single_line_from_caption_artifact():
    assert decide_image_class("图2-1-5 M4出土铜鼎（M4：6）纹饰", None) == "single_line_artifact"


def test_single_plate_from_note_artifact():
    assert decide_image_class("图版一 器物", "1. 罐（M4:1）") == "single_plate_artifact"


def test_multi_line_from_note_artifacts():
    note = "1. 陶豆（M4:1） 2. 陶壶（M4:2）"
    assert decide_image_class("图一 出土器物", note) == "multi_line_artifact"


def test_multi_plate_from_note_artifacts():
    note = "1. 罐（M4:1） 2. 壶（M4:2）"
    assert decide_image_class("图版一 器物", note) == "multi_plate_artifact"


def test_caption_artifact_fallback_when_note_no_art():
    # 图注只有视图名无器物号，图题有机物号 → rule_b/整图归属 → 单件
    note = "1. 舟腹部 2. 舟圈足"
    assert decide_image_class("图九 铜舟（M4:2）纹饰", note) == "single_line_artifact"

"""V0.3 S2 five-class image type refinement tests."""
from __future__ import annotations

from archaeopairs.parsers.keywords import refine_image_type


def test_single_line_refined():
    assert refine_image_type("line_drawing", "图2-1-5 M4出土铜鼎（M4：6）纹饰", None) == "single_line"


def test_multi_line_refined():
    note = "1. 陶豆（M4:1） 2. 陶壶（M4:2）"
    assert refine_image_type("line_drawing", "图一 出土器物", note) == "multi_line"


def test_single_plate_refined():
    assert refine_image_type("plate_artifact", "图版一 器物", "1. 罐（M4:1）") == "plate_artifact"


def test_multi_plate_refined():
    assert refine_image_type("plate_artifact", "图版一 器物", "1. 罐（M4:1） 2. 壶（M4:2）") == "multi_plate"


def test_plate_scene_refined():
    assert refine_image_type("plate_artifact", "图版一 墓葬场景", None) == "plate_scene"


# ---------- B2: XML 器物号信号优先于 VLM 视觉判定（rule_b 序号歧义前置消解） ----------


def test_vlm_multi_line_downgraded_to_single_by_xml_single_artifact():
    """VLM 判 multi_line，但 XML（图题）声明唯一器物号 → rule_b/单器物整图归属。"""
    assert refine_image_type("multi_line", "图2-1-5 M4出土铜鼎（M4：6）纹饰", None) == "single_line"


def test_vlm_single_line_upgraded_to_multi_by_xml_multi_artifact():
    """VLM 判 single_line，但 XML 图注声明多器物 → multi_line。"""
    note = "1. 陶豆（M4:1） 2. 陶壶（M4:2）"
    assert refine_image_type("single_line", "图一 出土器物", note) == "multi_line"


def test_no_xml_signal_keeps_visual_single():
    """无 XML 信号时不因序号个数歧义升降级（rule_b 多视图 vs 多器物不可由序号判）。"""
    note = "1. 舟腹部 2. 舟圈足"  # rule_b 视图名，无器物号
    assert refine_image_type("single_line", "图九 铜舟纹饰", note) == "single_line"
    assert refine_image_type("multi_line", "图九 铜舟纹饰", note) == "multi_line"


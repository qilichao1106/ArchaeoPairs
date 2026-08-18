"""V0.4.1 图类判定测试：XML 器物号 = 主信号、像素/关键词定线彩家族、五分类命名。"""
from __future__ import annotations

from archaeopairs.parsers.image_classify import classify_image_type


def test_no_artifact_discarded():
    assert classify_image_type("图一 出土器物", None) == "discarded"
    assert classify_image_type("图版三 墓葬全景", None) == "discarded"  # plate_scene 并入


def test_single_line_from_caption_artifact():
    assert classify_image_type("图2-1-5 M4出土铜鼎（M4：6）纹饰", None) == "single_line_artifact"


def test_single_plate_from_note_artifact():
    # 图题含"图版"关键词（无图像时回退关键词定线彩）→ 彩版族
    assert classify_image_type("图版一 器物", "1. 罐（M4:1）") == "single_plate_artifact"


def test_multi_line_from_note_artifacts():
    note = "1. 陶豆（M4:1） 2. 陶壶（M4:2）"
    assert classify_image_type("图一 出土器物", note) == "multi_line_artifact"


def test_multi_plate_from_note_artifacts():
    note = "1. 罐（M4:1） 2. 壶（M4:2）"
    assert classify_image_type("图版一 器物", note) == "multi_plate_artifact"


def test_caption_artifact_fallback_when_note_no_art():
    # 图注只有视图名无器物号，图题有机物号 → rule_b/整图归属 → 单件
    note = "1. 舟腹部 2. 舟圈足"
    assert classify_image_type("图九 铜舟（M4:2）纹饰", note) == "single_line_artifact"


def test_image_path_photo_forces_plate_family(tmp_path):
    # 像素判彩色 → 彩版族（即便图题无"图版"、不含关键词）
    from PIL import Image

    img = Image.new("RGB", (100, 80), (200, 20, 20))
    p = tmp_path / "c.png"
    img.save(p)
    assert classify_image_type("图二 器物", "1. 罐（M4:1）", p) == "single_plate_artifact"
    assert classify_image_type("图二 器物", "1. 罐（M4:1） 2. 壶（M4:2）", p) == "multi_plate_artifact"


def test_image_path_line_keeps_line(tmp_path):
    from PIL import Image

    img = Image.new("RGB", (100, 80), (255, 255, 255))  # 白底 → 线图
    for x in range(60):
        img.putpixel((x, 40), (0, 0, 0))
    p = tmp_path / "l.png"
    img.save(p)
    assert classify_image_type("图一 器物", "1. 陶豆（M4:1）", p) == "single_line_artifact"


def test_bad_image_path_falls_back_to_keyword():
    # 图像不可读 → 关键词回退（图题含"图版" → 彩版族）
    assert classify_image_type("图版一 器物", "1. 罐（M4:1）", "/nonexistent/x.jpg") == "single_plate_artifact"


def test_tuopian_hint_forces_line(tmp_path):
    # 方案A：图题带"拓片"→ 强制线图族，即使像素（全帧灰度梯度→gray照片）判灰
    from PIL import Image

    img = Image.new("RGB", (100, 80), (255, 255, 255))
    for x in range(100):
        v = int(255 * x / 100)
        for y in range(80):
            img.putpixel((x, y), (v, v, v))
    p = tmp_path / "tuo.png"
    img.save(p)
    assert classify_image_type(
        "图七 M3出土铜钱（拓片）", "1.康熙通宝（M3：1-1） 2.乾隆通宝（M3：1-2)", p
    ) == "multi_line_artifact"
    assert classify_image_type("图四一一 M220出土铜钱（拓片）", "1. 康熙通宝（M220：1-1）", p) == "single_line_artifact"


def test_tuopian_hint_in_note_forces_line():
    # 拓片词在图注也会触发；N=2 → multi_line_artifact
    assert classify_image_type("图 二 铭文（拓本）", "1. 铭文（M3：1） 2. 铭文（M3：2）", None) == "multi_line_artifact"


def test_lineart_hint_pure():
    from archaeopairs.parsers.image_classify import has_lineart_hint

    assert has_lineart_hint("图二 铭文（拓本）", None)
    assert has_lineart_hint("图 三 器物线描图", "1. 纹饰")
    assert has_lineart_hint("图 四 文字摹写", None)
    assert not has_lineart_hint("图 五 器物照片", "1. 罐（M4:1）")


def test_color_not_overridden_by_tuopian(tmp_path):
    # 组合规则：像素判 color → 彩版族，拓图词不得将其降为线图（避免误伤彩色图版）
    from PIL import Image

    img = Image.new("RGB", (100, 80), (200, 20, 20))
    p = tmp_path / "c.png"
    img.save(p)
    assert classify_image_type("图 六 器物线描对照（彩色版）", "1. 罐（M4:1）", p) == "single_plate_artifact"

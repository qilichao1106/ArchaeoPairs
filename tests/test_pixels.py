"""parsers/image_classify 像素家族判定测试（合成图像，确定性）。"""
from __future__ import annotations

from PIL import Image

from archaeopairs.parsers.image_classify import detect_family


def _new(w=100, h=80, mode="RGB", bg=(255, 255, 255)) -> Image.Image:
    return Image.new(mode, (w, h), bg)


def test_plain_white_is_line():
    assert detect_family(_new()) == "line"


def test_color_fill_is_color():
    img = _new()
    img.paste((200, 20, 20), (0, 0, 100, 80))
    assert detect_family(img) == "color"


def test_grayscale_gradient_is_gray():
    # 全帧横向过渡：白→黑，铺满画面（照片特征），白体素占比低
    img = _new()
    for x in range(100):
        v = int(255 * x / 100)
        for y in range(80):
            img.putpixel((x, y), (v, v, v))
    assert detect_family(img) == "gray"


def test_sparse_black_lines_is_line():
    # 白底稀疏墨线（线描图特征）
    img = _new()
    for x in range(60):
        img.putpixel((x, 40), (0, 0, 0))
    assert detect_family(img) == "line"

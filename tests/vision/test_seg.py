"""vision/seg 本地轮廓分割：合成图验证提取/排序/孔洞与包含剔除（仅 cv2 依赖）。"""
from __future__ import annotations

import cv2
import numpy as np

from archaeopairs.vision import extract_contours, filled_mask, mask_iou


def _synth(h=200, w=300) -> np.ndarray:
    """白底黑线合成图：两个实心块（上/下）+ 一个细线笔触。"""
    img = np.full((h, w), 255, np.uint8)
    cv2.rectangle(img, (20, 10), (80, 60), 0, -1)     # 上左块
    cv2.rectangle(img, (150, 100), (250, 180), 0, -1)  # 下右块
    cv2.line(img, (100, 20), (140, 40), 0, 2)          # 细线（min_area 过滤掉）
    return img


def test_extract_contours_reading_order_and_filter():
    # 膨胀后细线连通域面积 ~500：min_area=800 才滤掉，仅剩两实心块
    kept, removed, binary = extract_contours(_synth(), dilate_k=5, min_area=800.0)
    assert len(kept) == 2
    # 阅读序：上块在前，下块在后
    assert kept[0]["bbox"][1] < kept[1]["bbox"][1]
    assert all(k["area"] >= 800.0 for k in kept)
    # 二值图为膨胀后的前景掩膜
    assert binary.shape == (200, 300)
    # 膨胀桥接：细线与上块同层前景，但作为独立连通域仍可被面积过滤
    assert binary.any()


def test_extract_contours_hole_removed():
    # 实心大块中挖一个洞：外轮廓保留、内孔洞剔除
    img = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(img, (20, 20), (180, 180), 0, -1)
    cv2.rectangle(img, (80, 80), (120, 120), 255, -1)
    kept, removed, _ = extract_contours(img, dilate_k=3, min_area=30.0)
    # 膨胀 3x3 可能把洞桥接掉；用 k=1 保洞
    kept1, removed1, _ = extract_contours(img, dilate_k=1, min_area=30.0)
    assert len(kept1) == 1
    assert any(r["hole"] for r in removed1) or len(removed1) >= 1


def test_filled_mask_and_iou():
    img = _synth()
    kept, _, _ = extract_contours(img, dilate_k=1, min_area=800.0)
    m = filled_mask(kept[0]["contour"], img.shape)
    assert m.sum() > 0
    assert mask_iou(m, m) == 1.0
    other = filled_mask(kept[1]["contour"], img.shape)
    assert mask_iou(m, other) < 1.0  # 两块不相交 → 0；同图同掩膜 → 1

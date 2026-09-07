"""本地轮廓分割（自 archea_seg 迁移，去除远程 SAM 依赖）。

分割流程（技术方案 §4.4.1 前半）：OTSU 二值化 → 形态学膨胀（桥接离散线条）
→ 连通轮廓提取 → 孔洞/包含关系剔除。掩膜 = filled_mask 轮廓填充（无远程
模型细化）。SAM 远程提示点/NMS/实例合并（call_sam_points 等）不迁移。
"""
from __future__ import annotations

import cv2
import numpy as np


def extract_contours(gray, dilate_k: int = 5, min_area: float = 200.0):
    """二值化->膨胀->findContours->包含关系去除。

    返回 (kept, removed, binary)。去除规则：①连通域内部孔洞（hierarchy 有父）；
    ②小轮廓 bbox 四角均落在某更大轮廓多边形内（pointPolygonTest >= 0）。
    kept 按阅读序（上->下、左->右）排序，元素含 bbox/area/contour/hole。
    """
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_k, dilate_k))
    dilated = cv2.dilate(binary, kernel, iterations=1)
    contours, hierarchy = cv2.findContours(
        dilated, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    hier = hierarchy[0] if hierarchy is not None else np.empty((0, 4), dtype=np.int32)

    cands = []
    for i, c in enumerate(contours):
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        is_hole = hier[i][3] != -1  # 有父轮廓 = 孔洞/内含
        x, y, w, h = cv2.boundingRect(c)
        cands.append({"bbox": (x, y, x + w, y + h), "area": area,
                      "contour": c, "hole": is_hole})

    kept, removed = [], []
    for item in cands:
        if item["hole"]:
            removed.append(item)
            continue
        contained = False
        for other in cands:
            if other is item or other["hole"] or other["area"] <= item["area"]:
                continue
            x0, y0, x1, y1 = item["bbox"]
            corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
            if all(cv2.pointPolygonTest(other["contour"], (float(px), float(py)),
                                        False) >= 0 for px, py in corners):
                contained = True
                break
        (removed if contained else kept).append(item)
    kept.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))  # 阅读序：上->下、左->右
    return kept, removed, dilated


def contour_to_points(contour, n: int):
    """轮廓等弧长采样为 [[x,y,1],...] 正点序列（细长形退化用）。"""
    pts = contour.reshape(-1, 2).astype(float)
    if len(pts) < 3:
        return [[int(round(pts[0][0])), int(round(pts[0][1])), 1]]
    closed = np.vstack([pts, pts[:1]])
    seg = np.sqrt(((np.diff(closed, axis=0)) ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return [[int(round(pts[0][0])), int(round(pts[0][1])), 1]]
    out = []
    for t in np.linspace(0, total, n, endpoint=False):
        i = min(int(np.searchsorted(cum, t, side="right")) - 1, len(seg) - 1)
        r = (t - cum[i]) / seg[i] if seg[i] > 0 else 0.0
        p = closed[i] * (1 - r) + closed[i + 1] * r
        out.append([int(round(p[0])), int(round(p[1])), 1])
    return out


def filled_mask(contour, shape) -> np.ndarray:
    """轮廓填充掩膜（0/1），作为轮廓的区域表达与 IoU 基准。"""
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [contour], 1)
    return m


def mask_iou(a, b) -> float:
    inter = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    return inter / union if union else 0.0


def contour_poly(contour, eps: float = 1.0):
    """approxPolyDP 简化轮廓多边形，供 JSON 保留与回放。"""
    approx = cv2.approxPolyDP(contour, eps, True)
    return [[int(px), int(py)] for px, py in approx.reshape(-1, 2)]


def merge_overlapping_instances(entries, overlap_frac: float = 0.1):
    """重合/相交实例合并（全局后处理）。

    掩膜存在交集（交集面积 / 较小实例面积 > overlap_frac）的实例
    合并为一个（并集掩膜），合并前的小实例被吸收删除，score 取最大。
    完全不相交的实例保持独立。

    entries: [{"item": 轮廓dict, "score": float, "mask": bool ndarray}, ...]
    返回合并后的新列表（按掩膜面积降序；调用方可再按需排序）。
    """
    entries = [dict(e) for e in entries]
    changed = True
    while changed:
        changed = False
        entries.sort(key=lambda e: int(e["mask"].sum()), reverse=True)
        for i in range(len(entries)):
            for j in range(len(entries) - 1, i, -1):
                a, b = entries[i]["mask"], entries[j]["mask"]
                inter = int(np.logical_and(a, b).sum())
                if inter and inter / min(int(a.sum()), int(b.sum())) > overlap_frac:
                    # 小实例并入大实例（并集），小实例删除
                    entries[i]["mask"] = a | b
                    entries[i]["score"] = max(entries[i]["score"], entries[j]["score"])
                    entries.pop(j)
                    changed = True
    return entries

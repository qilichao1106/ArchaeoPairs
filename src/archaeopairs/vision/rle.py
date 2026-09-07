"""COCO 风格 RLE 编解码：bool 掩膜 <-> ASCII 字符串（MaskRecord.mask_rle 载体）。

列主序（Fortran）行程编码，格式 "{h}x{w}:{counts逗号表}"。
无第三方依赖（不引 pycocotools）；round-trip 必须逐像素精确（单测保证）。
"""
from __future__ import annotations

import numpy as np


def rle_encode(mask: np.ndarray) -> str:
    """bool/0-1 ndarray -> RLE 字符串（列主序，首行程必为背景 0 起算）。"""
    m = np.asarray(mask).astype(bool)
    h, w = m.shape
    flat = m.flatten(order="F")
    # 行程长度序列：首个行程属背景（COCO 约定），全前景时首行程为 0
    change = np.nonzero(np.diff(flat))[0] + 1
    edges = np.concatenate([[0], change, [flat.size]])
    counts = np.diff(edges).tolist()
    if flat[0]:
        counts = [0] + counts
    return f"{h}x{w}:" + ",".join(str(c) for c in counts)


def rle_decode(rle: str) -> np.ndarray:
    """RLE 字符串 -> bool ndarray（形状还原自前缀）。"""
    shape_part, counts_part = rle.split(":", 1)
    h, w = (int(v) for v in shape_part.split("x"))
    counts = [int(c) for c in counts_part.split(",")] if counts_part else []
    flat = np.zeros(h * w, dtype=bool)
    pos = 0
    val = False  # 首行程为背景
    for c in counts:
        if val:
            flat[pos:pos + c] = True
        pos += c
        val = not val
    if pos != h * w:
        raise ValueError(f"RLE 行程总长 {pos} != {h * w}")
    return flat.reshape((h, w), order="F")

"""图片读取工具（自 archea_seg 迁移）：多形态输入 + 中文路径安全。

Windows 中文路径下 cv2.imread 不可靠，一律 np.fromfile + imdecode。
"""
from __future__ import annotations

import os

import cv2
import numpy as np


def decode_image_bytes(data) -> "np.ndarray | None":
    """图片原始字节 -> BGR ndarray（格式自动识别：png/jpg/jpeg/bmp/webp/tif...）。"""
    arr = np.frombuffer(bytes(data), dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def load_image(image):
    """多形态输入 -> (BGR ndarray | None, 原始字节 | None)。

    支持：文件路径（任何 OpenCV 可解码格式，中文路径安全）、
    bytes/bytearray（图片原始字节）、BGR ndarray。
    """
    if isinstance(image, (str, os.PathLike)):
        path = os.fspath(image)
        data = open(path, "rb").read()
        return decode_image_bytes(data), data
    if isinstance(image, (bytes, bytearray)):
        return decode_image_bytes(image), bytes(image)
    if isinstance(image, np.ndarray):
        return np.ascontiguousarray(image), None
    return None, None


def png_base64(bgr_or_rgb) -> "str | None":
    """ndarray -> PNG base64（无需落盘）。"""
    ok, buf = cv2.imencode(".png", bgr_or_rgb)
    if not ok:
        return None
    import base64

    return base64.b64encode(buf.tobytes()).decode("ascii")

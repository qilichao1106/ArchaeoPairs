"""成图接口（对齐《技术方案 V0.5.1》成图规格（§7.3））。

P0 用 MockCompositor 写占位白底 PNG（验证命名/去重/对象存储链路）；
真实像素合成（掩膜抠图+白底+留白+旋转）为生产实现，接口不变。
"""
from __future__ import annotations

import base64
import zlib
from typing import Protocol

# 1x1 纯白 PNG（占位）
_WHITE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/"
    "aqskmgAAAABJRU5ErkJggg=="
)


def make_white_png(width: int = 8, height: int = 8) -> bytes:
    """生成纯白 PNG（标准库 zlib 构造，无第三方依赖）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return len(data).to_bytes(4, "big") + c + zlib.crc32(c).to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    idat = zlib.compress(raw)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


class Compositor(Protocol):
    def compose(self, *, image_path: str, masks: list[dict], trace_id: str) -> str: ...


class MockCompositor:
    """P0 占位成图：写白底 PNG 到对象存储，验证命名/去重/存储链路。"""

    def __init__(self, store) -> None:
        self._store = store

    def compose(self, *, image_path: str, masks: list[dict], trace_id: str) -> str:
        data = make_white_png()
        return self._store.put_bytes(image_path, data)

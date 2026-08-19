"""成图接口（对齐《技术方案 V0.5.1》成图规格（§7.3））。

P0 用 MockCompositor 写占位白底 PNG（验证命名/去重/对象存储链路）；
真实像素合成（掩膜抠图+白底+留白+旋转）为生产实现，接口不变。
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path
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
    def compose(self, *, image_path: str, masks: list[dict], trace_id: str,
                source: str | None = None) -> str: ...


class MockCompositor:
    """P0 成图：单器物(masks=[])且给 source → 拷贝原 media 图；否则白底占位。

    `source`: 源图绝对路径（S8 传 image_base/fileref）；masks 为空（整图=单器物
    Pair）→ `put(key, src)` 直接复制原图；masks 非空（多器物掩膜拆分）仍白底待实现。
    """

    def __init__(self, store) -> None:
        self._store = store

    def compose(self, *, image_path: str, masks: list[dict], trace_id: str,
                source: str | None = None) -> str:
        if not masks and source:
            src = Path(source)
            if src.is_file():
                return self._store.put(image_path, src)
        data = make_white_png()
        return self._store.put_bytes(image_path, data)

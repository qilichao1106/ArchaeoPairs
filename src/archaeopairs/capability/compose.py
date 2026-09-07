"""成图接口（对齐《技术方案 V0.5.1》成图规格（§7.3））。

MockCompositor 写占位白底 PNG（验证命名/去重/对象存储链路）；
PixelCompositor 真实像素合成（vision/compose.render_group：白底+掩膜贴
原像素+比例尺行置底+纯平移自检）。接口一致（compose 协议不变，
render_ctx 为真实路径可选透传）。
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
                source: str | None = None,
                render_ctx: dict | None = None) -> str: ...


class MockCompositor:
    """P0 成图：单器物(masks=[])且给 source → 拷贝原 media 图；否则白底占位。

    `source`: 源图绝对路径（S8 传 image_base/fileref）；masks 为空（整图=单器物
    Pair）→ `put(key, src)` 直接复制原图；masks 非空（多器物掩膜拆分）仍白底待实现。
    render_ctx（真实路径 S6 渲染上下文）忽略——mock 输出不受 provider 影响。
    """

    def __init__(self, store) -> None:
        self._store = store

    def compose(self, *, image_path: str, masks: list[dict], trace_id: str,
                source: str | None = None,
                render_ctx: dict | None = None) -> str:
        if not masks and source:
            src = Path(source)
            if src.is_file():
                return self._store.put(image_path, src)
        data = make_white_png()
        return self._store.put_bytes(image_path, data)


class PixelCompositor:
    """真实像素合成：render_ctx（S6 group_render_context 产物）驱动
    vision.compose.render_group；无 render_ctx 时与 MockCompositor 同形
    （masks 空+source → 拷原图；否则白底占位）。

    PNG 经 imencode+put_bytes 落对象存储（中文路径安全）；源图不可读抛
    E1100StorageError（统一拦截 PENDING_REVIEW，不静默出白图）。
    """

    def __init__(self, store, **cfg) -> None:
        from ..vision.compose import ComposeConfig

        self._store = store
        self.cfg = ComposeConfig(**cfg)

    def compose(self, *, image_path: str, masks: list[dict], trace_id: str,
                source: str | None = None,
                render_ctx: dict | None = None) -> str:
        if render_ctx is None:
            # mock 同形回退（单器物整图拷贝 / 白底占位）
            if not masks and source:
                src = Path(source)
                if src.is_file():
                    return self._store.put(image_path, src)
            return self._store.put_bytes(image_path, make_white_png())
        import cv2

        from ..errors import E1100StorageError
        from ..vision import load_image
        from ..vision.compose import render_group

        if not source:
            raise E1100StorageError(
                f"pixel compose: render_ctx 需要源图路径 ({image_path})")
        try:
            bgr, _ = load_image(source)
        except OSError as e:
            raise E1100StorageError(
                f"pixel compose: 源图不可读 {source} ({e})") from e
        if bgr is None:
            raise E1100StorageError(
                f"pixel compose: 源图解码失败 {source}")
        canvas, _rec = render_group(bgr, render_ctx, self.cfg)
        ok, buf = cv2.imencode(".png", canvas)
        if not ok:  # pragma: no cover
            raise E1100StorageError(f"pixel compose: PNG 编码失败 {image_path}")
        return self._store.put_bytes(image_path, buf.tobytes())

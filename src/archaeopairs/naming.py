"""成图命名规范（对齐《技术方案 V0.4》文件命名规范（§7.2））。

原图名=图题中图号部分；冒号归一为连字符；重名追加 _N。
图号归一化：空格剔除、"O/o/0" 后缀统一为 "〇"（"图二六O"→"图二六〇"）。
"""
from __future__ import annotations

import re

# 图号：图/圖 + 中文数字/章序式/点号式 + 可选字母/数字后缀
_FIG_RE = re.compile(r"(图|圖)\s*([0-9]+(?:[-.][0-9]+)*|[一二三四五六七八九十百千〇两]+)([a-zA-Z0-9])?")


def canonical_fig_text(text: str | None) -> str:
    """图号引用归一（用于正文图引用匹配）：去空格、O/o→〇。"""
    if not text:
        return ""
    return (text.replace(" ", "").replace("\u3000", "")
            .replace("O", "〇").replace("o", "〇"))


def extract_fig_number(caption: str | None, fallback: str = "") -> str:
    """从图题提取图号（剔除描述性汉字），后缀完整保留并归一 O/o/0→〇。"""
    if caption:
        m = _FIG_RE.search(caption)
        if m:
            suffix = m.group(3) or ""
            if suffix in ("O", "o", "0"):
                suffix = "〇"
            return f"{m.group(1)}{m.group(2)}{suffix}"
    return fallback or "图"


def path_artifact(artifact_id: str) -> str:
    """器物号冒号（:：∶）归一为连字符，Windows 兼容。"""
    return re.sub(r"[:：∶]", "-", artifact_id)


def build_image_name(fig_number: str, seq: str | None, artifact_id: str) -> str:
    """原图名_图片内序号_器物号.png；无图片内序号（单器物/整图归属）时序号段固定占位 01（§7.2）。"""
    parts = [fig_number]
    parts.append(str(seq) if seq is not None else "01")
    parts.append(path_artifact(artifact_id))
    return "_".join(parts) + ".png"


def dedup_name(name: str, registry: dict[str, int]) -> str:
    """重名防冲突：同名追加 _1/_2...（在扩展名前插入）。registry 须为 book 级共享。"""
    stem, dot, ext = name.rpartition(".")
    n = registry.get(stem, 0)
    registry[stem] = n + 1
    if n == 0:
        return name
    return f"{stem}_{n}.{ext}"

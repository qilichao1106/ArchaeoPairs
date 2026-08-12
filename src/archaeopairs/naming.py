"""成图命名规范（对齐《技术方案 V0.1》§7.2）。

原图名=图题中图号部分；冒号归一为连字符；重名追加 _N。
"""
from __future__ import annotations

import re

# 图号：图/圖 + 中文数字/章序式/点号式 + 可选字母后缀
_FIG_RE = re.compile(r"(图|圖)\s*([0-9]+(?:[-.][0-9]+)*|[一二三四五六七八九十百千〇两]+)([a-zA-Z])?")


def extract_fig_number(caption: str | None, fallback: str = "") -> str:
    """从图题提取图号（剔除描述性汉字），后缀完整保留。"""
    if caption:
        m = _FIG_RE.search(caption)
        if m:
            suffix = m.group(3) or ""
            return f"{m.group(1)}{m.group(2)}{suffix}"
    return fallback or "图"


def path_artifact(artifact_id: str) -> str:
    """器物号冒号（:：∶）归一为连字符，Windows 兼容。"""
    return re.sub(r"[:：∶]", "-", artifact_id)


def build_image_name(fig_number: str, seq: str | None, artifact_id: str) -> str:
    """原图名_图片内序号_器物号.png。"""
    parts = [fig_number]
    if seq is not None:
        parts.append(str(seq))
    parts.append(path_artifact(artifact_id))
    return "_".join(parts) + ".png"


def dedup_name(name: str, registry: dict[str, int]) -> str:
    """重名防冲突：同名追加 _1/_2...（在扩展名前插入）。"""
    stem, dot, ext = name.rpartition(".")
    n = registry.get(stem, 0)
    registry[stem] = n + 1
    if n == 0:
        return name
    return f"{stem}_{n}.{ext}"

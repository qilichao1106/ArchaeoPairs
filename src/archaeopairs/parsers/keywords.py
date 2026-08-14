"""图类关键词判定（§4.2 决策表的无 VLM 兜底路径，§3.7）。

S1 构建 ground 与 S2 关键词兜底共用同一套关键词口径，避免两处漂移。
地层特例：图题含"地层/遗迹"但没有平面/剖面类否决词 → 强制 line_drawing。
"""
from __future__ import annotations

import re

PLATE_RE = re.compile(r"图版|圖版")
PLATE_SCENE_RE = re.compile(r"墓葬|室墓|夯土|发掘|场景|隔梁|地层|遗迹")
DISCARD_RE = re.compile(r"平面|剖面|墓室|地层|遗迹|区位|位置示意|分布")


def classify_caption(caption: str | None, has_items: bool) -> str:
    """图题关键词判定：plate_artifact / plate_scene / discarded / line_drawing。

    has_items：该图是否有解析出的图注条目（有器物条目时不因关键词否决，
    近似实现"视觉内容优先"与地层特例在 mock 侧的行为）。
    """
    c = caption or ""
    if PLATE_RE.search(c):
        return "plate_scene" if PLATE_SCENE_RE.search(c) else "plate_artifact"
    if DISCARD_RE.search(c) and not has_items:
        return "discarded"
    return "line_drawing"

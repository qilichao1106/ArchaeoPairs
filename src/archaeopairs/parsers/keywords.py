"""图类关键词判定（图类判定器（§4.2）决策表的无 VLM 兜底路径，服务级降级与熔断（§3.7））。

S1 构建 ground 与 S2 关键词兜底共用同一套关键词口径，避免两处漂移。
地层特例：图题含"地层/遗迹"但没有平面/剖面类否决词 → 强制 line_drawing。
"""
from __future__ import annotations

import re

PLATE_RE = re.compile(r"图版|圖版")
PLATE_SCENE_RE = re.compile(r"墓葬|室墓|夯土|发掘|场景|隔梁|地层|遗迹")
DISCARD_RE = re.compile(r"平面|剖面|墓室|地层|遗迹|区位|位置示意|分布")


def _artifact_signals(caption: str | None, figure_note: str | None) -> tuple[list[str], int]:
    """聚合 XML 器物号信号：返回 (去重器物号列表, 图注序号计数)。"""
    from .s3_note import extract_caption_artifacts, parse_note

    items = parse_note(figure_note or "")
    note_arts = [a for it in items for a in it.artifact_ids]
    note_seq_count = sum(len(it.seq_list) or 1 for it in items)
    caption_arts = [] if note_arts else extract_caption_artifacts(caption)
    unique = list(dict.fromkeys(note_arts + caption_arts))
    return unique, note_seq_count


def refine_image_type(image_type: str, caption: str | None, figure_note: str | None) -> str:
    """单/多器物判定精化（图类判定器（§4.2）/ B2 rule_b 序号歧义前置消解）。

    线图家族以「XML 器物号个数」为单/多判定的唯一可靠信号：
    * 唯一器物号 → single_line（rule_b/整图归属，即便视觉见多个视图序号）；
    * 多个器物号 → multi_line；
    * 无 XML 信号 → 沿用视觉判定 image_type——此时"图内序号个数"对 rule_b
      多视图与多器物有歧义（§评审 B2），不得据此升降级。
    彩板家族维持原判定（图版场景 → plate_scene；多号/多序号 → multi_plate）。
    """
    unique, note_seq_count = _artifact_signals(caption, figure_note)
    if image_type in ("line", "line_drawing", "single_line", "multi_line"):
        if len(unique) == 1:
            return "single_line"
        if len(unique) > 1:
            return "multi_line"
        return image_type
    if image_type in ("plate", "plate_artifact"):
        if PLATE_SCENE_RE.search(caption or ""):
            return "plate_scene"
        return "multi_plate" if (len(unique) > 1 or note_seq_count > 1) else "plate_artifact"
    return image_type


def classify_caption(caption: str | None, has_items: bool, figure_note: str | None = None) -> str:
    """图题关键词判定：plate_artifact / plate_scene / discarded / line_drawing。

    has_items：该图是否有解析出的图注条目（有器物条目时不因关键词否决，
    近似实现"视觉内容优先"与地层特例在 mock 侧的行为）。
    """
    c = caption or ""
    if PLATE_RE.search(c):
        base = "plate_artifact"
    elif DISCARD_RE.search(c) and not has_items:
        base = "discarded"
    else:
        base = "line_drawing"
    return refine_image_type(base, caption, figure_note)

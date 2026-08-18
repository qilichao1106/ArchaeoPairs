"""图类判定（图类判定器（§4.2），V0.4.1 修订——以 XML 器物号为主、关键词定线/彩家族）。

判定总纲：
* XML 器物号个数 N = 图注∪图题去重唯一器件号，为第一级信号：
    N==0 -> discarded（不猜测，直接归档）；
    N==1 -> 单器件（single_*_artifact）；N>=2 -> 多器件（multi_*_artifact）。
* 线/彩家族由关键词 图版/圖版 判定（visual 不参与 S2 判定；plate_scene 并入 discarded，
  line_drawing 哨兵移除，枚举精简为 5 类）。无 VLM，服务级降级（§3.7）= 同一关键词路径。

S1 构建 ground 与 S2 共用同一 decide_image_class，避免两处漂移。
"""
from __future__ import annotations

import re

PLATE_RE = re.compile(r"图版|圖版")


def decide_image_class(caption: str | None, figure_note: str | None) -> str:
    """由 XML 图题+图注判图类（五分类之一）。器物号优先取图注，图注无号时图题兜底。"""
    from .s3_note import extract_caption_artifacts, parse_note

    items = parse_note(figure_note or "")
    note_arts = [a for it in items for a in it.artifact_ids]
    caption_arts = [] if note_arts else extract_caption_artifacts(caption)
    unique = list(dict.fromkeys(note_arts + caption_arts))
    n = len(unique)
    if n == 0:
        return "discarded"
    is_plate = bool(PLATE_RE.search(caption or ""))
    if n == 1:
        return "single_plate_artifact" if is_plate else "single_line_artifact"
    return "multi_plate_artifact" if is_plate else "multi_line_artifact"

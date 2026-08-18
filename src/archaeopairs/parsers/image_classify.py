"""图片 5 分类判定（V0.4.1，合并自原 keywords.py + capability/pixels.py）。

单一入口 `classify_image_type(caption, figure_note, image_path)` 即出五分类，
S2 等上游只调用本函数，不做内部功能识别。

判定：
* 器物号主判 N = 图注∪图题去重依托器物号个数（图注有号优先，图注无号时图题兜底）。
    N==0 -> discarded（不猜测，直接归档）
* 线/彩家族：
    a) 提供 image_path -> 真实像素判 line/gray/color；gray/color（照片）视为彩版族、line（线描）
       线图族。拓图词(拓片|拓本|拓印|线描|摹写)与像素**组合**使用：像素判 gray 但图题/图注含
       拓图词 -> 升级为线图族；像素判 line -> 线图族；像素判 color -> 彩版族（关键词不覆盖强彩色）。
    b) image_path 缺失或不可读 -> 回退关键词 图版/圖版 定线彩（并由拓图词强制线图）。
    N==1 -> single_*_artifact；N>=2 -> multi_*_artifact。

像素家族算法（参考 16,160 图三分类，numpy 向量化）：
* 最长边 96px thumbnail 降采样（色度/中间调为全局统计量，几乎无影响、大幅提速）；
* 逐像素通道极差 d = max(R,G,B)-min(R,G,B)；汇总 mean_chroma、pct20(d>20 占比%)；
  亮度 L=(R+G+B)/3，中间调 mid_ratio = L∈(64,192) 像素占比(%)——线图(双峰白底+黑线)
  中间调极少，灰度照片(连续影调)中间调高。
* 判定：彩色 pct20>=5 或 (mean_chroma>=8 且 pct20>=1)；
         非彩色 mid_ratio>=15 -> 灰度照片(gray)；否则 -> 线图(line)。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

try:
    import numpy as np
except ImportError:  # pragma: no cover - 纯 Python 回退
    np = None  # type: ignore[assignment]

from PIL import Image

PLATE_RE = re.compile(r"图版|圖版")

# 显式"线图/拓图"语义词：命中即在像素判定前强制 line（线图族）。
# 用于回退像素无法区分的子类（铜钱拓片等高中间调线图被误判灰度照片）。
LINEART_HINT_RE = re.compile(r"拓片|拓本|拓印|线描|摹写")


def has_lineart_hint(caption: str | None, figure_note: str | None) -> bool:
    """图题/图注是否明确标注为拓图/线描（优先级最高，强制归线图族）。"""
    text = f"{caption or ''} {figure_note or ''}"
    return bool(LINEART_HINT_RE.search(text))

# 像素家族判定常量（参考 21 书 16,160 图校准阈值）
CHROMA_TH = 20            # 通道极差超过该值视为"明显带色像素"
MID_LO, MID_HI = 64, 192  # 中间调亮度区间(排除近白/近黑)
COLOR_PCT_TH = 5.0
COLOR_MEAN_TH = 8.0
COLOR_MIN_PCT = 1.0
MID_TH = 15.0             # 中间调占比阈值：灰度照片 vs 线图
CONF_COLOR_PCT = 10.0     # 置信度边界
CONF_MID_LOW = 28.0
CONF_MID_HIGH = 8.0


# ---- 像素家族（numpy 向量化，纯 Python 兜底） ----
def _stats(img: Image.Image) -> Tuple[float, float, float]:
    im = img.convert("RGB")
    im.thumbnail((96, 96))
    w, h = im.size
    n = w * h
    if n == 0:
        return 0.0, 0.0, 0.0
    if np is not None:
        a = np.asarray(im, dtype=np.int16)
        d = a.max(axis=-1) - a.min(axis=-1)
        mean = float(d.mean())
        pct = float((d > CHROMA_TH).sum()) / n * 100.0
        lum = a.mean(axis=-1)
        mid = float(((lum > MID_LO) & (lum < MID_HI)).sum()) / n * 100.0
        return mean, pct, mid
    # 纯 Python 兜底
    px = list(im.getdata())
    dsum = over = mid = 0
    for r, g, b in px:
        d = max(r, g, b) - min(r, g, b)
        dsum += d
        if d > CHROMA_TH:
            over += 1
        lum0 = (r + g + b) / 3.0
        if MID_LO < lum0 < MID_HI:
            mid += 1
    return dsum / n, over / n * 100.0, mid / n * 100.0


def _decide(mean: float, pct: float, mid: float) -> str:
    if pct >= COLOR_PCT_TH or (mean >= COLOR_MEAN_TH and pct >= COLOR_MIN_PCT):
        return "color"
    return "gray" if mid >= MID_TH else "line"


def _conf(fam: str, pct: float, mid: float) -> str:
    if fam == "color":
        return "low" if pct < CONF_COLOR_PCT else "high"
    if fam == "gray":
        return "low" if mid < CONF_MID_LOW else "high"
    return "low" if mid > CONF_MID_HIGH else "high"


def detect_family(img: Image.Image) -> str:
    """对已载入 PIL Image 判三族（line/gray/color）。"""
    return _decide(*_stats(img))


def detect_family_conf(img: Image.Image) -> Tuple[str, str]:
    """判三族并给置信度 high/low（低置信建议人工复核）。"""
    mean, pct, mid = _stats(img)
    return _decide(mean, pct, mid), _conf(_decide(mean, pct, mid), pct, mid)


def family_of(path: str | Path) -> str:
    """按文件路径判三族；文件无法读取/损坏时抛 OSError（调用方回退关键词）。"""
    with Image.open(str(path)) as img:
        return detect_family(img)


# ---- 器物号计数 ---- #
def count_artifacts(caption: str | None, figure_note: str | None) -> int:
    from . import s3_note

    items = s3_note.parse_note(figure_note or "")
    note_arts = [a for it in items for a in it.artifact_ids]
    caption_arts = [] if note_arts else s3_note.extract_caption_artifacts(caption)
    return len(list(dict.fromkeys(note_arts + caption_arts)))


# ---- 单一入口：5 分类 ----
def classify_image_type(caption: str | None, figure_note: str | None,
                        image_path: str | Path | None = None) -> str:
    """返回五分类之一：single_line/single_plate/multi_line/multi_plate/discarded（均 _artifact）。"""
    n = count_artifacts(caption, figure_note)
    if n == 0:
        return "discarded"
    explicit_line = has_lineart_hint(caption, figure_note)
    fam: str | None = None
    if image_path:
        try:
            fam = family_of(image_path)
        except (OSError, ValueError, ImportError):
            fam = None
    if fam is not None:
        # 组合：像素为骨架，拓图词仅作歧义消解——
        # * 像素判 line -> 线图族（无论关键词）；
        # * 像素判 gray(黑白照片) 但图题/图注明确拓片|拓本|拓印|线描|摹写 -> 升级为线图族；
        # * 像素判 color -> 彩版族（关键词不覆盖强彩色信号，避免误伤彩色图版）。
        if fam == "color":
            is_plate = True
        elif fam == "gray":
            is_plate = not explicit_line
        else:  # fam == "line"
            is_plate = False
    else:
        # 无图/不可读：唯一信号是关键词（此时拓图词单独生效属无选择余地）
        is_plate = (not explicit_line) and bool(PLATE_RE.search(caption or ""))
    if n == 1:
        return "single_plate_artifact" if is_plate else "single_line_artifact"
    return "multi_plate_artifact" if is_plate else "multi_line_artifact"

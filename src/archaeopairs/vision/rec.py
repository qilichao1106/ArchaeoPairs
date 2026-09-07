"""S5 识别器算法层（自 archea_rec 迁移）：比例尺/数字序号/说明文字识别。

调用方传入分割轮廓 kept（vision.seg.extract_contours 结果）→ 几何 + 本地
PaddleOCR（PP-OCRv6_medium_rec，唯一可用后端，异常即报警不静默降级）分类：
  * 比例尺组 = 尺体（细长带刻度齿）+ 起点"0" + "x厘米"值文本；左侧前缀数字
    （"1、2. 0——4厘米"）按正文序号独立输出（scale_prefix 标记）；
  * 非比例尺区：纯数字→serials；digits_only=True（默认）只识别数字序号，
    文字/字母读值归 others(text)；
  * 噪声碎片抑制（scale_zone/fig_zone/tiny/sliver/lowconf/line）入 others。
输出 dict 结构见 ArcheaRec.recognize docstring（原文件头注释，git 历史可溯）。
"""

import base64
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("FLAGS_use_mkldnn", "0")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _local_paddle_model_dir():
    """Prefer a project-local PaddleX cache so sandboxed runs can read models."""
    cache = _PROJECT_ROOT / ".paddlex_cache"
    model_dir = cache / "official_models" / "PP-OCRv6_medium_rec"
    if model_dir.is_dir():
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        return model_dir
    return None


@contextmanager
def _paddle_static_compatibility():
    """Bypass the PIR-memory-opt path that fails with paddle 3.3.1 + PP-OCRv6."""
    from paddlex.inference.models.runners.paddle_static.runner import (
        PaddleStaticRunner,
    )

    def _create_cpu(self):
        import paddle.inference as paddle_inference
        from paddlex.inference.models.utils.model_paths import get_model_paths

        model_file, params_file = get_model_paths(
            self.model_dir, self.model_file_prefix)["paddle"]
        # Paddle Inference fails to read UTF-8 absolute paths on this Windows env.
        model_file = Path(model_file).resolve().relative_to(_PROJECT_ROOT)
        params_file = Path(params_file).resolve().relative_to(_PROJECT_ROOT)
        config = paddle_inference.Config(str(model_file), str(params_file))
        config.disable_gpu()
        config.disable_mkldnn()
        config.set_cpu_math_library_num_threads(
            int(self._config.get("cpu_threads") or 10))
        config.disable_glog_info()
        return paddle_inference.create_predictor(config)

    original = PaddleStaticRunner._create
    old_cwd = os.getcwd()
    os.chdir(_PROJECT_ROOT)
    PaddleStaticRunner._create = _create_cpu
    try:
        yield
    finally:
        PaddleStaticRunner._create = original
        os.chdir(old_cwd)

import cv2
import numpy as np

from .images import load_image
from .seg import extract_contours


# ---------------------------------------------------------------------------
# 参数（可被 ArcheaRec.__init__ kwargs 覆盖）
# ---------------------------------------------------------------------------
DEFAULTS = dict(
    dilate_k=5,          # [推荐值] archea_seg.extract_contours 膨胀核（调用方分割用）
    min_area=15,         # [推荐值] extract_contours 轮廓最小面积（数字笔画下限）
    comp_maxdim=90,      # 文字组件最大边长（超过视为图形）
    comp_mindim=3,       # 文字组件最小边长（噪声下限）
    comp_area=4000,      # 文字组件最大面积
    fig_maxdim=90,       # >= 视为图形大轮廓（器物线图）
    fig_area=4000,       # >= 视为图形大轮廓
    bar_med_thick=14,    # 尺体线身中位厚度上限（px）
    bar_min_span=30,     # 尺体净长下限（横尺）
    bar_min_span_v=70,   # 尺体净长下限（竖尺；防长数字/竖线误判）
    bar_max_w_v=30,      # 竖尺 bbox 最大宽度（更宽多为装饰边框/纹饰列）
    bar_span_ar=3.5,     # 尺体净长/最大厚度 比 下限
    bar_area=8000,       # 尺体组件面积上限
    bar_min_ticks=2,     # 刻度齿数下限（docx：必须为带刻度的图形化标尺）
    band_up=18,          # 尺行带向上扩展（容纳线上方数字/文字）
    band_dn=12,          # 尺行带向下扩展
    band_side=16,        # 尺行带左右扩展
    zero_gap=48,         # 起点"0"距尺端最大距离
    value_gap=34,        # 值文本距尺端最大距离
    prefix_ext=150,      # 尺起点侧搜索范围（起点"0"与行带判定用）
    merge_dx=12,         # 横向合并：x 间距
    merge_dy=8,          # 横向合并：y 基线差
    merge_dy_v=6,        # 纵向合并：y 间距（竖排文字）
    merge_dx_v=6,        # 纵向合并：中心 x 距
    fig_zone_margin=10,  # 图形贴边抑制区：组件纵向在图形跨度内且水平间隙<=该值
                         # （阴影带/虚线刻度等图内碎片常凸出器身轮廓数px）
    fig_zone_vtol=12,    # 图内判定纵向容差：横向在图形跨度内、纵向越界<=该值
                         # 仍视为图内碎片（贴上/下边缘的虚线刻度残笔）
    bar_zone_pad=0,      # 尺体抑制区：与已证认尺体 bbox 相交(含该容差)的未吸收
                         # 单元视为尺上碎片（起点0误读/刻度残笔），不作物序号。
                         # 取0：前缀序号距尺体可近至1px，容差会误吞前缀
    norm_maxdim=128,     # 单元裁片主档：最大边(宽或高)归一化目标（只放大；
                         # 序号类单元"小而高" p50≈37px，高度档仅~1.3×放大
                         # 读不出淡印小字，最大边档~3.5×——OCR尺寸实验结论）
    norm_h=48,           # 基准高度档：尺行带默认取 1.5×=72（宽行须按高度放大，
                         # 最大边规则下宽>128 的行永不放大，会丢尺值，见 _band_crop）
    norm_h_alt=96,       # 双尺度第二档（小单元互补救援，见 _read_units）
    small_maxdim=40,     # 双尺度读值的小单元尺寸上限
    alt_min_conf=0.85,   # alt 档读值的最低置信度（防幻觉：低分且无单位词不取）
    pad=8,               # 裁片白边 padding
    digits_only=True,    # 只识别数字序号：文字/字母读值归 others(text) 不进 texts
    tick_ratio=1.6,      # 刻度齿判定：墨厚 > 中位厚 * tick_ratio
)

# 单位词表：读值含任一词 -> 比例尺文字（正则交替序：长词在前）
UNIT_RE = r"(厘米|毫米|公分|微米|nm|cm|mm|dm|米)"
UNIT_WORDS = ("厘米", "毫米", "公分", "微米", "cm", "mm", "dm", "米")
# 尺主体："0——4厘米"（0 与数值间可有破折号/波浪号/空格）
BAR_RE = re.compile(r"0\s*[-—–_~～]*\s*(\d+(?:\.\d+)?)\s*" + UNIT_RE, re.I)
# 退化主体（无起点 0）："4厘米"
BAR_NOZERO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*" + UNIT_RE, re.I)
# 前缀/序号形态：数字 + 顿号/点/横线/波浪分隔
SERIAL_RE = re.compile(r"^(?:\d{1,2}\s*[、.,，\-—－~～]?\s*){1,4}$")
# 器物号形态（全局编号）：M4:6 / M2:1
RELIC_RE = re.compile(r"^[Mm]\d+\s*[:：]\s*\d+$")
ZERO_TXT = ("0", "O", "o", "〇", "○", "。")


def _has_unit(t):
    """读值是否含单位词（比例尺文字核心证据）。"""
    tl = (t or "").lower()
    return any(u.lower() in tl for u in UNIT_WORDS)


def _box_intersects(a, b, m=0):
    """两 bbox [x0,y0,x1,y1] 是否相交（各边含容差 m）。"""
    return (a[0] <= b[2] + m and b[0] <= a[2] + m
            and a[1] <= b[3] + m and b[1] <= a[3] + m)


def check_serial_set(serials):
    """序号集合校验（1..N 近似连续；与 ocr_reader.check_serial_set 同义）。

    serials: [str,...] 已读出的序号值（可重复）。返回
    {"nums","missing","dups","suspect"}，元素均为 str。
    """
    nums = [int(s) for s in serials if s and s.isdigit()]
    uniq = sorted(set(nums))
    dups = sorted({n for n in nums if nums.count(n) > 1})
    if not uniq:
        return {"nums": [], "missing": [], "dups": [], "suspect": []}
    missing = [n for n in range(1, uniq[-1] + 1) if n not in set(uniq)]
    median = uniq[len(uniq) // 2]
    suspect = [n for n in uniq if n > 2 * median + 2]
    return {"nums": [str(n) for n in uniq], "missing": [str(n) for n in missing],
            "dups": [str(n) for n in dups], "suspect": [str(n) for n in suspect]}


def _clean_prefix(head):
    """头部片段 -> 前缀序号串（白名单：数字、顿号、~、-、.、空格）。

    沿用 ocr_reader._clean_prefix：'.' 视为前缀点号归一为顿号；
    含字母/其它字符时视为非前缀，返回空串。
    """
    head = (head or "").strip(" .。,，;；:：　 ")
    head = re.sub(r"[a-zA-Z]", "", head)
    if not head:
        return ""
    head = head.replace(".", "、")
    if re.match(r"^[\d、~～\-－—\s]+$", head):
        return re.sub(r"\s+", "", head.rstrip("、~～-－—"))
    return ""


def _parse_scale_text(t):
    """尺行整行读值 -> {"prefix","text","value","unit"}（白名单解析）。

    优先匹配带起点 0 的尺主体（"0——4厘米"，强证据），其前段为前缀；
    否则退化匹配 "数值单位"。粘连修复沿用 ocr_reader：'1、2. 0——4厘米'
    连读成 '1.204厘米' 时，数值 204 中第一个 '0' 是尺起点，'0' 前部分
    归前缀、其后是尺值（'204' -> 前缀'2' + 起点'0' + 尺值'4'）。
    """
    out = {"prefix": "", "text": "", "value": None, "unit": None}
    t = (t or "").strip()
    if not t:
        return out
    m = BAR_RE.search(t)
    if not m:
        # 起点 0 被误读为下划线/破折号连写（'__3厘米'）：行首横杠归一为 '0—' 再匹配
        t2 = re.sub(r"^[\s_\-—–~～]+", "0—", t)
        if t2 != t:
            m = BAR_RE.search(t2)
            if m:
                t = t2
    if m:
        out.update(prefix=_clean_prefix(t[:m.start()]), text=m.group(0),
                   value=float(m.group(1)), unit=m.group(2))
        return out
    m2 = BAR_NOZERO_RE.search(t)
    if not m2:
        return out
    num_str, unit = m2.group(1), m2.group(2)
    head = t[:m2.start()]
    # 整数粘连：数值中间含 '0'（非首非尾）-> 从第一个 '0' 拆：'0' 是尺起点
    k = num_str.find("0")
    if 0 < k < len(num_str) - 1:
        new_val = num_str[k + 1:]
        if new_val and float(new_val) < 50:      # 尺值合理性（厘米级）
            return {"prefix": _clean_prefix(head + num_str[:k]),
                    "text": "0—" + new_val + unit,
                    "value": float(new_val), "unit": unit}
    return {"prefix": _clean_prefix(head), "text": m2.group(0),
            "value": float(num_str), "unit": unit}


# ---------------------------------------------------------------------------
# OCR 后端（可插拔 rec-only）
# ---------------------------------------------------------------------------
class OcrBackend:
    """rec-only 识别后端：仅 paddle（paddleocr TextRecognition，PP-OCRv6）。

    rapidocr 已停用（其内置 PP-OCRv4 效果低于 PP-OCRv6，回退会造成识别
    效果降级）；"none"（无 OCR 纯几何）同样停用——无读值时序号/比例尺
    识别必然缺失，属无效识别。backend 仅允许 "auto"|"paddle"（等价）。
    报警策略：backend 非法（none/rapid/其他）、paddleocr 初始化失败或
    识别调用失败 => 立即抛异常报警（消息带 ⚠ 报警 前缀），拒绝静默
    降级、拒绝产出空读值结果。
    """

    def __init__(self, backend="auto"):
        self.name = "none"
        self.error = None            # 最近一次报警原因（诊断用）
        self._paddle = None
        if backend not in ("auto", "paddle"):
            raise ValueError(
                f"⚠ 报警：OCR 后端 {backend!r} 不可用（rapidocr 已停用防效果"
                "降级，'none' 无读值属无效识别），仅允许 backend ∈ {auto, paddle}")
        try:
            self._init_paddle()
            self.name = "paddle"
        except Exception as e:
            self.error = f"paddle: {type(e).__name__}: {e}"
            raise RuntimeError(
                "⚠ 报警：paddleocr 不可用，识别管线拒绝降级运行"
                "（rapidocr/none 均已禁用，无回退后端）。\n"
                f"  原因: {self.error}\n"
                "  处理: 安装/修复 paddlepaddle(>=3.0, CPU 版) 后重试。") from e

    def _init_paddle(self):
        model_dir = _local_paddle_model_dir()
        from paddleocr import TextRecognition
        with _paddle_static_compatibility():
            try:
                kwargs = {"model_name": "PP-OCRv6_medium_rec",
                          "enable_mkldnn": False}
                if model_dir is not None:
                    kwargs["model_dir"] = str(model_dir)
                self._paddle = TextRecognition(**kwargs)
            except TypeError:
                self._paddle = TextRecognition()

    def recognize(self, crops):
        """裁片列表 -> [(text, conf), ...]；调用失败 => 报警（抛异常）。"""
        if not crops:
            return []
        if self.name == "none":
            return [("", 0.0)] * len(crops)
        try:
            outs = list(self._paddle.predict(crops))
            return [(str(o.get("rec_text", "")).strip(),
                     float(o.get("rec_score", 0.0))) for o in outs]
        except Exception as e:
            raise RuntimeError(
                "⚠ 报警：paddleocr 识别调用失败，拒绝返回空读值结果："
                f"{type(e).__name__}: {e}") from e


# ---------------------------------------------------------------------------
# 主类：轮廓提取 -> 几何分类 -> 单元 OCR -> 比例尺组合 -> 序号/文本
# ---------------------------------------------------------------------------
class ArcheaRec:
    """考古线图轮廓分类识别（比例尺 / 序号 / 文本；可视化见 archea_show_rec.py）。"""

    def __init__(self, ocr=None, backend=None, **kw):
        self.p = dict(DEFAULTS)
        self.p.update(kw)
        env_backend = os.environ.get("ARCHEA_OCR_BACKEND", "auto")
        self.ocr = ocr or OcrBackend(backend or env_backend)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    @staticmethod
    def _accept_kept(kept):
        """承接 archea_seg 结果：归一化为 extract_contours 的 kept 列表。

        支持三种形态：
          ① kept 列表（extract_contours 第 1 返回值，元素含 bbox/area/contour）；
          ② extract_contours() 三元组返回值 (kept, removed, binary)；
          ③ ArcheaSeg().segment() 结果 dict（由 instances[].contour_poly 重建；
             SAM 相交合并吸收掉的小组件不会出现，仅作兼容入口）。
        缺失/为空/形态不识别 => 报警（ValueError）。
        """
        if isinstance(kept, dict) and "instances" in kept:
            items = []
            for it in kept["instances"]:
                poly = it.get("contour_poly")
                if not poly:
                    continue
                items.append({"bbox": list(it["bbox"]),
                              "area": float(it.get("area") or 0.0),
                              "contour": np.asarray(poly, np.int32).reshape(-1, 2)})
            kept = items
        elif (isinstance(kept, (tuple, list)) and len(kept) == 3
                and isinstance(kept[0], (list, tuple))):
            kept = kept[0]               # extract_contours 三元组返回值
        if not kept:
            raise ValueError(
                "⚠ 报警：recognize 未收到分割结果 kept——archea_rec 已改为"
                " archea_seg 的下游独立模块，不再自行调用 extract_contours；"
                "请由调用方先执行 archea_seg 分割并传入其结果"
                "（extract_contours 的 kept / 三元组 / ArcheaSeg segment() dict）。")
        first = kept[0]
        if not (isinstance(first, dict) and "contour" in first):
            raise ValueError(
                f"⚠ 报警：kept 元素形态不识别（{type(first).__name__}），"
                "须为含 bbox/area/contour 的轮廓项"
                "（见 archea_seg.extract_contours 返回结构）。")
        return kept

    def recognize(self, image, kept=None):
        """单图完整识别（分割结果由调用方传入，本模块不再自行分割）。

        image：路径/bytes/BGR ndarray（仅用于 OCR 裁片与可视化）。
        kept：archea_seg 分割结果（三选一，见 _accept_kept）；缺失/为空 => 报警。
        返回 dict 见模块头注释。
        """
        t0 = time.time()
        kept = self._accept_kept(kept)
        bgr, _upload = load_image(image)
        if bgr is None:
            return {"ok": False, "error": "imread failed", "backend": self.ocr.name,
                    "image_size": None, "scales": [], "serials": [], "texts": [],
                    "figures": [], "others": [],
                    "serial_set": check_serial_set([]),
                    "stats": {"n_contours": 0, "n_figures": 0, "n_bars": 0,
                              "n_scales": 0, "n_serials": 0, "n_texts": 0,
                              "n_others": 0, "latency_s": round(time.time() - t0, 3)}}
        H, W = bgr.shape[:2]

        # 1) 几何预分类（轮廓已由调用方经 archea_seg 提取并滤噪）
        bars, figures, comps = self._geometry(kept)

        # 2) 文字组件合并成单元 + 逐单元 OCR（竖高单元自动加试 90° 旋转）
        units = self._merge_units(comps)
        reads = self._read_units(bgr, units)   # 与 units 一一对应

        # 3) 比例尺组合（尺体 + 0 + 值文本 + 左侧前缀数字 / 纯文字尺寸标注）
        scales, used = self._group_scales(bars, reads, bgr)

        # 4) 非比例尺区域：序号 / 文本 / 未定（含噪声碎片抑制）
        rest = [r for i, r in enumerate(reads) if i not in used]
        bar_zones = [b["bbox"] for b in bars if b.get("claimed")]
        fig_zones = [f["bbox"] for f in figures]
        serials, texts, others = self._classify_rest(rest, bar_zones, fig_zones)
        # 尺体候选中被降级的长线（无任何证据、齿数不足）归入 others.line
        for b in bars:
            if not b.get("claimed"):
                others.append({"bbox": list(b["bbox"]), "reason": "line",
                               "text": "", "conf": 0.0})

        scales.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        for i, s in enumerate(scales):
            s["id"] = i
        for i, x in enumerate(serials):
            x["id"] = i
        for i, x in enumerate(texts):
            x["id"] = i

        return {
            "ok": True, "error": None, "backend": self.ocr.name,
            "image_size": [W, H],
            "scales": scales, "serials": serials, "texts": texts,
            "figures": [{"bbox": list(f["bbox"]), "area": round(f["area"], 1)}
                        for f in figures],
            "others": others,
            "serial_set": check_serial_set(
                [x["no"] for x in serials if not x.get("scale_prefix")]),
            "stats": {
                "n_contours": len(kept), "n_figures": len(figures),
                "n_bars": len(bars), "n_scales": len(scales),
                "n_serials": len(serials), "n_texts": len(texts),
                "n_others": len(others),
                "latency_s": round(time.time() - t0, 3)},
        }

    # ------------------------------------------------------------------
    # 几何预分类：尺体候选（带刻度齿）/ 图形 / 文字组件
    # ------------------------------------------------------------------
    def _geometry(self, kept):
        """kept 轮廓 -> (bars, figures, comps)。

        尺体判据（顺序判定，先于图形——比例尺长度常超过图形阈值）：
          线身中位墨厚 <= bar_med_thick，净长 >= bar_min_span 且
          净长/最大墨厚 >= bar_span_ar，面积 <= bar_area，刻度齿 >= bar_min_ticks。
        刻度齿：沿尺轴向的墨厚剖面中，厚于中位厚 tick_ratio 倍的列（行）数
        ——尺端/中部的凸出刻度线（docx：比例尺必须为带刻度的图形化标尺）。
        """
        bars, figures, comps = [], [], []
        p = self.p
        for k in kept:
            x0, y0, x1, y1 = k["bbox"]
            w, h = x1 - x0, y1 - y0
            maxd, mind = max(w, h), min(w, h)
            prof, med, mx, span, ticks = self._bar_profile(k, w, h)
            min_span = p["bar_min_span"] if w >= h else p["bar_min_span_v"]
            if (span >= min_span and 0 < med <= p["bar_med_thick"]
                    and span >= p["bar_span_ar"] * mx and k["area"] <= p["bar_area"]
                    and (w >= h or w <= p["bar_max_w_v"])   # 竖尺须窄（防装饰列）
                    and ticks >= p["bar_min_ticks"]):
                bars.append({"bbox": [x0, y0, x1, y1], "area": k["area"],
                             "contour": k["contour"], "orient": "h" if w >= h else "v",
                             "med_thick": round(float(med), 2),
                             "max_thick": int(mx), "span": int(span),
                             "ticks": ticks, "claimed": False})
                continue
            if maxd >= p["fig_maxdim"] or k["area"] >= p["fig_area"]:
                figures.append(k)
                continue
            if maxd <= p["comp_maxdim"] and mind >= p["comp_mindim"] \
                    and k["area"] <= p["comp_area"]:
                comps.append({"bbox": [x0, y0, x1, y1], "area": k["area"],
                              "contour": k["contour"]})
                continue
            # 其余中等组件（未达图形阈值又不宜作文字）：归图形（不 OCR）
            figures.append(k)
        comps.sort(key=lambda c: (c["bbox"][1] // 15, c["bbox"][0]))
        return bars, figures, comps

    def _in_figure_zone(self, cb, fig_boxes, margin=None):
        """组件是否落在图形内/贴边碎片区（阴影带、虚线刻度、剖面线等）。

        inside：组件 bbox 完全在图形 bbox 内；
        side  ：组件纵向完全在图形纵向跨度内且水平间隙 <= margin
                （阴影带常凸出器身轮廓数px，纯包含判定漏滤）；
        edge  ：组件横向完全在图形横向跨度内、纵向越界 <= fig_zone_vtol
                （贴上/下边缘的虚线刻度残笔）。
        序号/说明文字通常位于图形下方或远离图形，不落入该 zone；
        真实序号落进不规则轮廓 bbox 空白角时由调用方按 读值形态 豁免。
        """
        margin = self.p["fig_zone_margin"] if margin is None else margin
        vtol = self.p["fig_zone_vtol"]
        for fb in fig_boxes:
            if cb[0] >= fb[0] and cb[1] >= fb[1] and cb[2] <= fb[2] and cb[3] <= fb[3]:
                return True
            gx = max(fb[0] - cb[2], cb[0] - fb[2], 0)
            if 0 < gx <= margin and cb[1] >= fb[1] and cb[3] <= fb[3]:
                return True
            if gx == 0 and cb[1] >= fb[1] - vtol and cb[3] <= fb[3] + vtol:
                return True
        return False

    def _bar1_is_connector(self, r, fig_zones, med_digit_h):
        """细长竖条读 '1'：连接符 vs 数字 1 的上下文判别。

        实测本数据集中数字 '1' 常画作无斜帽的等宽竖条，形态上与视图连接
        线完全相同（top/body=1.0），只能靠上下文区分：
          ① 完全落在某图形 bbox 内部 -> 连接符（图内指引线残段）；
          ② 高度显著大于本图其他数字序号（>= 1.5 倍中位数）-> 连接符
            （同一版面数字等高：真 '1' 与其他数字同高，连接线通常更长）。
        其余情况保守判为数字 '1'（不误杀）。med_digit_h 为 None（本图暂无
        其他数字）时只按 ① 判。
        """
        x0, y0, x1, y1 = r["bbox"]
        cx = (x0 + x1) / 2
        h = y1 - y0
        for fb in fig_zones:
            if fb[0] <= cx <= fb[2] and fb[1] <= y0 and y1 <= fb[3]:
                return True
        if med_digit_h is not None and h >= 1.5 * med_digit_h:
            return True
        return False

    def _mark_scale_prefix(self, sr, bar_zones):
        """序号标记：是否为比例尺左侧前缀数字（"1、2."/"1~2" 等）。

        判据：与某已证认尺体同尺行（纵向交叠含 8px 容差）且右缘位于该尺
        起点左侧 prefix_ext 像素内。标记写入 sr["scale_prefix"]（True/False），
        用于区分正文器物序号（docx 序号硬性匹配只计正文序号）。
        """
        x0, y0, x1, y1 = sr["bbox"]
        ext = self.p["prefix_ext"]
        for z in bar_zones:
            if (y1 >= z[1] - 8 and y0 <= z[3] + 8
                    and z[0] - ext <= x1 <= z[0] + 4):
                sr["scale_prefix"] = True
                return
        sr["scale_prefix"] = False

    @staticmethod
    def _bar_profile(k, w, h):
        """轮廓填充掩膜沿尺轴向的墨厚剖面 -> (prof, med, mx, span, ticks)。

        prof: 横尺按列求和 / 竖尺按行求和的墨厚数组；
        med/mx: 剖面中位值/最大值（线身厚度 / 刻度齿高）；
        span: 有墨的轴向长度（净长）；ticks: 厚于 med*tick_ratio 的列数。
        """
        x0, y0 = k["bbox"][0], k["bbox"][1]
        if w < 2 or h < 2 or len(k["contour"]) < 3:
            return None, 0, 0, 0, 0
        m = np.zeros((h, w), np.uint8)
        cv2.fillPoly(m, [k["contour"] - [x0, y0]], 1)
        # 横尺按列求和（每列墨厚）/ 竖尺按行求和（每行墨宽）
        prof = m.sum(axis=0 if w >= h else 1).astype(np.int32)
        pos = prof[prof > 0]
        if len(pos) == 0:
            return prof, 0, 0, 0, 0
        med = float(np.median(pos))
        mx = int(pos.max())
        span = int(len(pos))
        ticks = int((pos > med * 1.6).sum())
        return prof, med, mx, span, ticks

    # ------------------------------------------------------------------
    # 文字组件 -> 单元合并（横向行序 + 纵向竖排两遍）
    # ------------------------------------------------------------------
    def _merge_units(self, comps):
        """小组件合并成读值单元。

        第一遍横排（行序扫描）：gap_x ∈ [0, merge_dx] 且 y 基线差 <= merge_dy；
        负 gap（x 重叠/跨行远距组件）不得合并（003.png '3''4' 相距 509px
        仍并成 '34' 的教训，沿用 ocr_reader 修复）。
        第二遍纵排（竖排文字/上下紧邻笔画）：gap_y ∈ [0, merge_dy_v] 且
        中心 x 距 <= merge_dx_v；合并后保留 comps 供拆分读值。
        """
        units = []
        for c in comps:                                   # 第一遍：横排
            b = c["bbox"]
            if units:
                u = units[-1]
                gap_x = b[0] - u["bbox"][2]
                if 0 <= gap_x <= self.p["merge_dx"] \
                        and abs(b[1] - u["bbox"][1]) <= self.p["merge_dy"]:
                    u["bbox"] = [min(u["bbox"][0], b[0]), min(u["bbox"][1], b[1]),
                                 max(u["bbox"][2], b[2]), max(u["bbox"][3], b[3])]
                    u["comps"].append(c)
                    continue
            units.append({"bbox": list(b), "comps": [c]})
        units.sort(key=lambda u: (u["bbox"][0] // 15, u["bbox"][1]))
        merged = []                                       # 第二遍：纵排
        for u in units:
            if merged:
                v = merged[-1]
                gap_y = u["bbox"][1] - v["bbox"][3]
                vcx = (v["bbox"][0] + v["bbox"][2]) / 2
                ucx = (u["bbox"][0] + u["bbox"][2]) / 2
                if 0 <= gap_y <= self.p["merge_dy_v"] \
                        and abs(ucx - vcx) <= self.p["merge_dx_v"]:
                    v["bbox"] = [min(v["bbox"][0], u["bbox"][0]),
                                 min(v["bbox"][1], u["bbox"][1]),
                                 max(v["bbox"][2], u["bbox"][2]),
                                 max(v["bbox"][3], u["bbox"][3])]
                    v["comps"].extend(u["comps"])
                    continue
            merged.append(u)
        return merged

    # ------------------------------------------------------------------
    # 单元裁片 + OCR（竖高单元加试 90° 旋转，竖排文字支持）
    # ------------------------------------------------------------------
    def _unit_crop(self, bgr, box, pad=None, norm_h=None):
        """单元裁片：白边 padding + 归一化放大（只放大不缩小）。

        主档（norm_h=None）：按**最大边(宽或高)**归一化到 norm_maxdim；
        显式传 norm_h（alt 档/补试）：按高度归一化，保持双尺度互补。
        """
        H, W = bgr.shape[:2]
        pad = self.p["pad"] if pad is None else pad
        x0, y0 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
        x1, y1 = min(W, int(box[2]) + pad), min(H, int(box[3]) + pad)
        if x1 <= x0 or y1 <= y0:
            return None
        c = bgr[y0:y1, x0:x1]
        if norm_h is None:
            s = max(1.0, self.p["norm_maxdim"] / max(1, max(c.shape[0], c.shape[1])))
        else:
            s = max(1.0, norm_h / max(1, c.shape[0]))
        if s > 1.01:
            c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(c, pad, pad, pad, pad,
                                  cv2.BORDER_CONSTANT, value=(255, 255, 255))

    def _read_units(self, bgr, units):
        """逐单元读值。竖高单元（h >= 2.2*w）加试两个 90° 旋转，取高分。

        双尺度读值（rapid det 对小字敏感的对策）：小单元（maxdim <=
        small_maxdim）同时用主档（最大边 norm_maxdim）与 norm_h_alt
        （高度 96）两档各读一次，取 (含单位词, 置信度) 最优——实测同一
        数字在不同尺度下互补（002.png '7' 仅 96px 档读出、'5'/'2' 仅
        低档读出）；大单元首读为空时补试 norm_h_alt 一档。

        竖高单元三路读值决策：
          ① 旋转读值含单位词或以高分胜出 -> 竖排文字（rotated=True）；
          ② 直读为单个数字（断裂笔画并拢的情形，如裂成两截的 '1'）-> 直读；
          ③ 组件数 >= 2 且明显竖排堆叠 -> 拆回组件逐个读值（防止把上下
             相邻的两个序号并读成幻影序号 '12'）。
        返回与 units 一一对应的读值列表。
        """
        p = self.p
        jobs = []          # [(uidx, variant, crop)] variant: 0直读 1顺旋 2逆旋
        small = []         # 需要双尺度的小单元 uidx
        for i, u in enumerate(units):
            w = u["bbox"][2] - u["bbox"][0]
            h = u["bbox"][3] - u["bbox"][1]
            tall = h >= 2.2 * max(w, 1) and h >= 20
            c0 = self._unit_crop(bgr, u["bbox"])
            if c0 is None:
                continue
            jobs.append((i, 0, c0))
            if max(w, h) <= p["small_maxdim"]:        # 小单元：双尺度
                ca = self._unit_crop(bgr, u["bbox"], norm_h=p["norm_h_alt"])
                if ca is not None:
                    jobs.append((i, 3, ca))
                small.append(i)
            if tall:
                for vi, rot in ((1, cv2.ROTATE_90_CLOCKWISE),
                                (2, cv2.ROTATE_90_COUNTERCLOCKWISE)):
                    jobs.append((i, vi, cv2.rotate(c0, rot)))
        reads = [dict(bbox=u["bbox"], comps=u["comps"], text="", conf=0.0,
                      rotated=False) for u in units]
        if not jobs:
            return reads
        res = self.ocr.recognize([j[2] for j in jobs])
        best = {}          # uidx -> (variant, text, conf)
        for (i, vi, _c), (t, s) in zip(jobs, res):
            if vi == 3 and s < p["alt_min_conf"] and not _has_unit(t):
                continue  # alt 档防幻觉门卫：低分且无单位词不取
            # 单位词证据优先于置信度（比例尺文字关键特征）；conf 两位小数
            # 打平（rapid 各档分差常在千分位，平局保留先到的低档读值）
            if i not in best or (_has_unit(t), round(s, 2)) > \
                    (_has_unit(best[i][1]), round(best[i][2], 2)):
                best[i] = (vi, t, s)
        # 读值为空 -> 补试基准高度档 norm_h（48）：最大边档的过放大插值
        # 对个别小字（如范围前缀 '9.'）反而失读，低档恰好读出（互补三档）
        retry_jobs = []
        for i, (vi, t, s) in list(best.items()):
            u = units[i]
            if (not t and max(u["bbox"][2] - u["bbox"][0],
                              u["bbox"][3] - u["bbox"][1]) > p["small_maxdim"]):
                ca = self._unit_crop(bgr, u["bbox"], norm_h=p["norm_h_alt"])
                if ca is not None:
                    retry_jobs.append((i, 3, ca))
            elif not t:
                cb = self._unit_crop(bgr, u["bbox"], norm_h=p["norm_h"])
                if cb is not None:
                    retry_jobs.append((i, 3, cb))
        if retry_jobs:
            for (i, vi, _c), (t, s) in zip(
                    retry_jobs, self.ocr.recognize([j[2] for j in retry_jobs])):
                if s < p["alt_min_conf"] and not _has_unit(t):
                    continue
                if (_has_unit(t), round(s, 2)) > \
                        (_has_unit(best[i][1]), round(best[i][2], 2)):
                    best[i] = (vi, t, s)
        # ③ 竖排堆叠拆分：组件逐个读值，结果各自成独立读值
        split_jobs, split_map = [], []
        for i, (vi, t, s) in best.items():
            u = units[i]
            w = u["bbox"][2] - u["bbox"][0]
            h = u["bbox"][3] - u["bbox"][1]
            digit_only = re.sub(r"[、.,，\-—－~～\s]", "", t)
            if (vi == 0 and len(u["comps"]) >= 2 and h >= 2.2 * max(w, 1)
                    and len(digit_only) >= 2 and digit_only.isdigit()):
                for c in u["comps"]:
                    cc = self._unit_crop(bgr, c["bbox"])
                    if cc is not None:
                        split_jobs.append(cc)
                        split_map.append(i)
        split_res = self.ocr.recognize(split_jobs) if split_jobs else []
        split_by_uidx = {}
        for i, (t, s) in zip(split_map, split_res):
            split_by_uidx.setdefault(i, []).append((t, s))

        for i, (vi, t, s) in best.items():
            r = reads[i]
            if i in split_by_uidx:                    # 拆分成独立读值（替换本单元）
                items = split_by_uidx[i]
                r["text"] = "".join(x[0] for x in items)
                r["conf"] = min(x[1] for x in items) if items else 0.0
                r["split"] = [{"text": a, "conf": round(b, 3), "bbox": None}
                              for a, b in items]
                continue
            r["text"], r["conf"] = t.strip(), float(s)
            r["rotated"] = vi in (1, 2)
        return reads

    # ------------------------------------------------------------------
    # 比例尺组合
    # ------------------------------------------------------------------
    def _band_crop(self, bgr, box, orient, rot=None, norm_h=None):
        """尺行带裁片：组 bbox 外扩（含线上方数字带），竖尺先旋转为横排。"""
        H, W = bgr.shape[:2]
        p = self.p
        # 尺行带宽常>128（p50≈270），按高度放大（1.5×=72）；
        # 若按最大边则永不放大，小字号尺值会漏读（003 实测回退）
        norm_h = p["norm_h"] * 1.5 if norm_h is None else norm_h
        if orient == "h":
            x0 = max(0, int(box[0]) - p["band_side"])
            x1 = min(W, int(box[2]) + p["band_side"] + 8)
            y0 = max(0, int(box[1]) - p["band_up"])
            y1 = min(H, int(box[3]) + p["band_dn"])
        else:
            x0 = max(0, int(box[0]) - p["band_dn"])
            x1 = min(W, int(box[2]) + p["band_up"])
            y0 = max(0, int(box[1]) - p["band_side"])
            y1 = min(H, int(box[3]) + p["band_side"] + 8)
        if x1 <= x0 or y1 <= y0:
            return None
        c = bgr[y0:y1, x0:x1]
        s = max(1.0, norm_h / max(1, c.shape[0]))   # 带裁片放大更激进
        if s > 1.01:
            c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        c = cv2.copyMakeBorder(c, p["pad"], p["pad"], p["pad"], p["pad"],
                               cv2.BORDER_CONSTANT, value=(255, 255, 255))
        if rot is not None:
            c = cv2.rotate(c, rot)
        return c

    def _read_band(self, bgr, box, orient):
        """尺行带整行读值：横尺 1 路；竖尺两个旋向各 1 路取最优。

        首轮读值不含单位词（或为空）时，补试 norm_h_alt 放大档（与单元
        双尺度同理：同一行文字在不同尺度下互补）。最优判据：含单位词
        优先，其次置信度。返回 (text, conf, rotated)。
        """
        p = self.p
        if orient == "h":
            variants = [("h", None)]
        else:
            variants = [("v", cv2.ROTATE_90_CLOCKWISE),
                        ("v", cv2.ROTATE_90_COUNTERCLOCKWISE)]
        crops = [(o, r, self._band_crop(bgr, box, o, r)) for o, r in variants]
        crops = [c for c in crops if c[2] is not None]
        if not crops:
            return "", 0.0, False
        res = self.ocr.recognize([c[2] for c in crops])
        bt, bs = "", 0.0
        for (_o, _r, _c), (t, s) in zip(crops, res):
            if (_has_unit(t), round(s, 2)) > (_has_unit(bt), round(bs, 2)):
                bt, bs = t, s
        if not _has_unit(bt) or not bt:                   # 补试放大档
            crops2 = [(o, r, self._band_crop(bgr, box, o, r,
                                             norm_h=p["norm_h_alt"]))
                      for o, r in variants]
            crops2 = [c for c in crops2 if c[2] is not None]
            if crops2:
                res2 = self.ocr.recognize([c[2] for c in crops2])
                for (_o, _r, _c), (t, s) in zip(crops2, res2):
                    if s < p["alt_min_conf"] and not _has_unit(t):
                        continue
                    if (_has_unit(t), round(s, 2)) > (_has_unit(bt), round(bs, 2)):
                        bt, bs = t, s
        return bt.strip(), float(bs), orient == "v"

    def _group_scales(self, bars, reads, bgr):
        """比例尺组合。返回 (scales, used_unit_indices)。

        比例尺组 = 尺体 + 起点"0" + "x厘米"值文本（横尺；竖尺 x/y 角色对调）：
          值文本：尺端外侧 value_gap 内、读值含单位词的单元；
          起点 0：尺起点外侧 zero_gap 内、读值为 0（含 O/〇）的小单元；
          band 整行读值兜底解析（0/值粘连修复，_parse_scale_text）。
        比例尺左侧的前缀数字（"1、2."/"1~2" 等）不属于比例尺——不做归属，
        留给 _classify_rest 按数字序号（serial）独立输出。
        无尺体但含单位词的未吸收单元 -> kind='text' 纯文字尺寸标注。
        无任何证据的尺体候选：band 读出单位词 -> 升级 verified；
        否则 ticks>=3 保留为未证认候选（verified=False，交人工复核），
        ticks<3 降级为普通长线（others.line）。
        """
        p = self.p
        scales, used = [], set()

        def y_ov(a, b, m=0):                     # y 向重叠长度（含 m 容差）
            return min(a[3], b[3]) - max(a[1], b[1]) + m

        def x_ov(a, b, m=0):
            return min(a[2], b[2]) - max(a[0], b[0]) + m

        def is_zero(r):
            t = re.sub(r"[\s.。,，]", "", r["text"])
            return t in ZERO_TXT and (r["bbox"][2] - r["bbox"][0]) <= 34 \
                and (r["bbox"][3] - r["bbox"][1]) <= 34

        def claim(ridx, role, members):
            used.add(ridx)
            members.append({"role": role, "bbox": reads[ridx]["bbox"],
                            "text": reads[ridx]["text"],
                            "conf": round(reads[ridx]["conf"], 3)})

        for bi, bar in enumerate(bars):
            bb = bar["bbox"]
            horiz = bar["orient"] == "h"
            members = [{"role": "bar", "bbox": bb, "text": "", "conf": 1.0}]
            if horiz:   # 行带（y 重叠判定用）
                band = [bb[0] - p["prefix_ext"], bb[1] - p["band_up"],
                        bb[2] + p["value_gap"] + 20, bb[3] + p["band_dn"]]
            else:
                band = [bb[0] - p["band_dn"], bb[1] - p["prefix_ext"],
                        bb[2] + p["band_up"], bb[3] + p["value_gap"] + 20]

            zero_i = value_i = None
            for ri, r in enumerate(reads):
                if ri in used or not r["text"]:
                    continue
                rb = r["bbox"]
                if not (x_ov(rb, band) > 0 and y_ov(rb, band) > 0):
                    continue
                if horiz:
                    left_of = rb[2] <= bb[0] + 12         # 单元在尺起点左侧（容差12）
                    right_of = rb[0] >= bb[2] - 18        # 单元在尺终点右侧（容差18）
                    dist_start = bb[0] - rb[2]            # 距尺起点
                    dist_end = rb[0] - bb[2]              # 距尺终点
                else:                                     # 竖尺：y 角色对调
                    left_of = rb[3] <= bb[1] + 12         # 单元在尺起点上方
                    right_of = rb[1] >= bb[3] - 18        # 单元在尺终点下方
                    dist_start = bb[1] - rb[3]
                    dist_end = rb[1] - bb[3]
                if value_i is None and right_of and _has_unit(r["text"]) \
                        and dist_end <= p["value_gap"] + 12:
                    value_i = ri
                elif zero_i is None and left_of and is_zero(r) \
                        and dist_start <= p["zero_gap"]:
                    zero_i = ri
            # 比例尺左侧的前缀数字（"1、2." 等）不归入比例尺（用户更新）：
            # 不吸收、不进 members，留给 _classify_rest 按数字序号独立输出。

            has_evidence = value_i is not None or zero_i is not None
            if not has_evidence:
                # band 兜底读值：读出单位词 -> 证认；否则按齿数决定保留/降级
                bt, bs, brot = self._read_band(bgr, bb, bar["orient"])
                parsed = _parse_scale_text(bt)
                if parsed["value"] is not None or _has_unit(bt):
                    bar["claimed"] = True
                    scales.append(self._scale_entry(
                        "bar", bar, bb, bt, bs, parsed, members, bgr, brot))
                elif bar["ticks"] >= 3:
                    bar["claimed"] = True
                    scales.append(self._scale_entry(
                        "bar", bar, bb, bt, bs,
                        {"text": "", "value": None, "unit": None},
                        members, bgr, brot, verified=False))
                continue                                  # 未证认：不进 scales

            if zero_i is not None:
                claim(zero_i, "zero", members)
            if value_i is not None:
                claim(value_i, "value", members)
            # 组包围盒 = 尺体 + 起点0 + 值文本（前缀数字不参与）
            gx0 = min([bb[0]] + [m["bbox"][0] for m in members[1:]])
            gy0 = min([bb[1]] + [m["bbox"][1] for m in members[1:]])
            gx1 = max([bb[2]] + [m["bbox"][2] for m in members[1:]])
            gy1 = max([bb[3]] + [m["bbox"][3] for m in members[1:]])
            # band 整行读值（组 bbox 外扩），解析 0/值（前缀段忽略）
            band_box = [gx0, gy0, gx1, gy1]
            bt, bs, brot = self._read_band(bgr, band_box, bar["orient"])
            parsed = _parse_scale_text(bt)
            # 值/单位：值文本成员读值优先（干净单元， conf 高），缺失或读不出
            # 时保留 band 整行解析结果（0/值粘连修复，_parse_scale_text）
            if value_i is not None:
                pv = _parse_scale_text(reads[value_i]["text"])
                if pv["value"] is not None:
                    parsed["value"], parsed["unit"] = pv["value"], pv["unit"]
                    parsed["text"] = reads[value_i]["text"]
            bar["claimed"] = True
            scales.append(self._scale_entry(
                "bar", bar, [gx0, gy0, gx1, gy1], bt, bs, parsed, members,
                bgr, brot))

        # 纯文字尺寸标注：含单位词且未被任何尺组吸收的单元
        for ri, r in enumerate(reads):
            if ri in used or not _has_unit(r["text"]):
                continue
            used.add(ri)
            rb = r["bbox"]
            pv = _parse_scale_text(r["text"])
            orient = "h" if (rb[2] - rb[0]) >= (rb[3] - rb[1]) else "v"
            scales.append({
                "kind": "text", "orientation": orient, "bbox": list(rb),
                "bar_bbox": None, "ticks": 0,
                "text": pv["text"] or r["text"], "raw_text": r["text"],
                "value": pv["value"], "unit": pv["unit"],
                "conf": round(r["conf"], 3), "verified": True,
                "members": [{"role": "value", "bbox": list(rb),
                             "text": r["text"], "conf": round(r["conf"], 3)}],
                "crop_base64": None, "contour_poly": None, "id": len(scales)})
        return scales, used

    def _scale_entry(self, kind, bar, bbox, raw, conf, parsed, members, bgr,
                     rotated=False, verified=True):
        """比例尺组条目构造（含尺行裁片与尺体轮廓多边形）。"""
        crop = self._band_crop(bgr, bbox, bar["orient"]) if kind == "bar" else None
        return {
            "kind": kind, "orientation": "v" if rotated else bar["orient"],
            "bbox": [int(v) for v in bbox],
            "bar_bbox": list(bar["bbox"]), "ticks": bar["ticks"],
            "text": parsed["text"], "raw_text": raw,
            "value": parsed["value"], "unit": parsed["unit"],
            "conf": round(conf, 3), "verified": verified,
            "members": members,
            "crop_base64": _png_base64(crop) if crop is not None else None,
            "contour_poly": contour_poly(bar["contour"]),
            "id": 0,
        }

    # ------------------------------------------------------------------
    # 非比例尺区域分类：序号 / 文本 / 未定
    # ------------------------------------------------------------------
    def _classify_rest(self, reads, bar_zones=(), fig_zones=()):
        """剩余读值单元 -> (serials, texts, others)。

        尺上碎片：与已证认尺体 bbox 相交（容差 bar_zone_pad）的未吸收单元
        -> others(scale_zone)（起点0误读、刻度残笔，不作物序号/文本）；
        起点0紧贴尺起点左侧（不交尺体）的极小单元同样归 scale_zone；
        与前缀粘连并读的单元（'1、2.0'）先按字符占比切出前缀独立成序号；
        图内碎片：落在图形内/贴边区（_in_figure_zone：阴影带、虚线刻度、
        剖面线等）-> others(fig_zone)；1-2 位纯数字且 h>=12 的序号形态豁免
        （不用 conf 门槛：rapid 对小字读值置信度普遍偏低）；
        微小噪点：maxdim <= 10 的非序号读值 -> others(tiny)；
        连接符：读作 '1' 的细长竖条（数字 '1' 与视图连接线形态相同）先暂存，
        循环后按上下文统一判别（_bar1_is_connector：图形内部 或 高于本图
        其他数字 1.5 倍 -> others(connector)，做出标识防混入序号）；
        纯数字（可带 、.－ 分隔）-> 序号 serial（no 取首个 1-2 位数），并
        标记 scale_prefix（是否为比例尺左侧前缀数字，区分正文序号）；
        尺寸/形状门卫：细长条（h>3.5w）低置信多为图线碎片 -> others(sliver)；
        过小/过大的其余数字形态 -> others(lowconf)；
        器物号形态 M4:6 -> text 且 relic=True（全局编号，非图内序号）；
        其余可读 -> 说明文字 text；读不出 -> other（unreadable）。
        digits_only=True（默认）时不做文字/字母识别：text/relic 读值一律
        归 others(reason="text")，texts 恒为空。
        序号匹配前先归一化读值（去空格/引号杂符："1 ~3.'" -> "1~3."）。
        """
        serials, texts, others = [], [], []
        bar1_candidates = []               # 读 '1' 的细长竖条（连接符候选）
        pad = self.p["bar_zone_pad"]
        digits_only = self.p["digits_only"]
        for r in reads:
            t = (r["text"] or "").strip()
            t = re.sub(r"[\s'\"`]+", "", t)      # 归一化：去空格/引号杂符
            if not t:
                others.append({"bbox": list(r["bbox"]), "reason": "unreadable",
                               "text": "", "conf": round(r["conf"], 3)})
                continue
            w_ = r["bbox"][2] - r["bbox"][0]
            h_ = r["bbox"][3] - r["bbox"][1]
            # --- 尺上碎片隔离（scale_zone） ---
            zb = next((z for z in bar_zones
                       if _box_intersects(r["bbox"], z, pad)), None)
            if zb is None:
                # 起点0紧贴尺起点左侧（不交尺体）：极小单元且右缘抵近尺起点
                zb = next((z for z in bar_zones
                           if w_ <= 10 and h_ <= 10
                           and z[0] - 8 <= r["bbox"][2] <= z[0] + 4
                           and r["bbox"][1] <= z[3] + 6
                           and z[1] <= r["bbox"][3] + 6), None)
            if zb is not None:
                # 前缀粘连：前缀与起点0并读成单元（'1、2.0'）时切出前缀独立成序号
                mpre = re.match(r"^((?:\d{1,2}\s*[、.,，\-—－~～]\s*)+)", t)
                if mpre and w_ >= 20 and r["bbox"][0] <= zb[0] - 10:
                    pre = mpre.group(1).strip()
                    m = re.search(r"\d{1,2}", pre)
                    px1 = max(r["bbox"][0] + 1,
                              r["bbox"][0] + int(round(w_ * len(pre) / len(t))))
                    serials.append({"bbox": [r["bbox"][0], r["bbox"][1],
                                             px1, r["bbox"][3]],
                                    "text": pre, "conf": round(r["conf"], 3),
                                    "rotated": r.get("rotated", False),
                                    "no": m.group(0) if m else ""})
                else:
                    others.append({"bbox": list(r["bbox"]),
                                   "reason": "scale_zone",
                                   "text": t, "conf": round(r["conf"], 3)})
                continue
            item = {"bbox": list(r["bbox"]), "text": t,
                    "conf": round(r["conf"], 3), "rotated": r.get("rotated", False)}
            if RELIC_RE.match(t):
                if digits_only:
                    others.append(dict(item, reason="text"))
                else:
                    texts.append(dict(item, relic=True))
                continue
            # 序号形态测试剥离前导分隔符：高倍放大档下邻接范围号/顿号的
            # 尾部会进入裁片读出 '.9.' 类前导点（image264 实测），数字
            # 信息不变，不剥离会误失序号/前缀
            serial_like = bool(
                SERIAL_RE.match(t.lstrip(r"、.,，\-—－~～ 	"))
                and any(ch.isdigit() for ch in t))
            # --- 图内/贴边碎片（fig_zone）：序号形态豁免 ---
            n_digits = len(re.sub(r"\D", "", t))
            if self._in_figure_zone(r["bbox"], fig_zones) and not (
                    serial_like and n_digits <= 2 and h_ >= 12):
                others.append({"bbox": list(r["bbox"]), "reason": "fig_zone",
                               "text": t, "conf": round(r["conf"], 3)})
                continue
            # --- 微小噪点（tiny） ---
            if not serial_like and max(w_, h_) <= 10:
                others.append({"bbox": list(r["bbox"]), "reason": "tiny",
                               "text": t, "conf": round(r["conf"], 3)})
                continue
            if serial_like:
                # --- 连接符候选：读作 '1' 的细长竖条（数字 1 与连接线形态
                #     相同，先暂存，循环结束后按上下文统一判别） ---
                if t == "1" and w_ <= 12 and h_ >= 20:
                    bar1_candidates.append((r, item))
                    continue
                # 形状门卫：细长条（h>3.5w）低置信多为图线碎片（sliver，
                # 限小单元：大竖条可能是数字 '1'，已走上方连接符判别）；
                # 尺寸门卫：过小细条/过大图形碎片（lowconf）
                sliver = h_ > 3.5 * max(w_, 1) and r["conf"] < 0.9 \
                    and max(w_, h_) <= 24
                if not sliver and max(w_, h_) <= 45 \
                        and ((h_ >= 12 and w_ >= 5) or r["conf"] >= 0.9):
                    m = re.search(r"\d{1,2}", t)
                    serials.append(dict(item, no=m.group(0) if m else ""))
                else:
                    others.append({"bbox": list(r["bbox"]),
                                   "reason": "sliver" if sliver else "lowconf",
                                   "text": t, "conf": round(r["conf"], 3)})
            elif digits_only:
                others.append(dict(item, reason="text"))   # 不识别文字/字母
            else:
                texts.append(dict(item, relic=False))
        # --- 细长竖条 '1' 的连接符/数字判别（需全图其他数字高度作参照） ---
        digit_hs = [s["bbox"][3] - s["bbox"][1] for s in serials
                    if s["no"].isdigit() and s["no"] != "1"]
        med_digit_h = float(np.median(digit_hs)) if digit_hs else None
        for r, item in bar1_candidates:
            if self._bar1_is_connector(r, fig_zones, med_digit_h):
                others.append({"bbox": list(r["bbox"]), "reason": "connector",
                               "text": item["text"], "conf": round(r["conf"], 3)})
            else:
                serials.append(dict(item, no="1"))
        serials.sort(key=lambda s: (s["bbox"][1] // 15, s["bbox"][0]))  # 阅读序
        for sr in serials:                     # 比例尺左侧前缀数字标记
            self._mark_scale_prefix(sr, bar_zones)
        return serials, texts, others


# ---------------------------------------------------------------------------
# 通用工具（输出编码 / 轮廓简化 / 读图；可视化已拆分至 archea_show_rec.py）
# ---------------------------------------------------------------------------
def _png_base64(img):
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


def contour_poly(contour, eps=1.0):
    """approxPolyDP 简化轮廓多边形（回放/调试用；语义同 archea_seg）。"""
    if contour is None or len(contour) < 3:
        return None
    approx = cv2.approxPolyDP(contour, eps, True)
    return [[int(px), int(py)] for px, py in approx.reshape(-1, 2)]


def imread_cn(path):
    """中文安全读图。"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

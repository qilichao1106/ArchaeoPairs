"""E1–E4 组装规则链（legacy/extract/archea_extract.py 迁移，V0.5.4）。

在分割（seg.extract_contours）与识别（rec.ArcheaRec）的基础上，把一张
图版中的各个器物分割为独立单元（纯算法层，不感知 LangGraph State 与
能力网关）：
  E1 build_assembly   原子收集：视图(轮廓+填充掩膜)/正文序号/比例尺组/
                      连接符；R1 小尺寸视图救援、R2 嵌套碎片吸收
                      （bbox+掩膜级 >=60% 真实包含，细长条豁免）
  E1.5 vl_review      规则证据冲突候选的 VL 仲裁（三态合并，留痕）
  E2 bind_labels      序号→视图归属：全部候选收集 + 全局贪心分配 +
                      R3b 刚性竞争置信度驱逐 + R3c 空白角墨迹纠正 +
                      R7 同号唯一（K1）+ E2.1 连接符继承（rank4）
  E2.5 rescue_missing_serials  序号漏读 VL 抢救（rank2 外部证据）
  E3 group_views      并查集分组：G1同序号 > G2连接符 > G3无标号组迭代
                      吸附 > G4带号单例吸附 > VL 兜底
  E4 bind_scales      比例尺分级绑定：L1前缀序号硬匹配 > L2唯一尺全局
                      共享 > L3 VL 读前缀兜底 > 放弃报警（R6 前缀解析加固）

vl 参数为 capability 协议仲裁器（providers.VlArbiterService；协议方法
judge_views/confirm_absorption/read_serials/same_artifact/read_scale_prefix，
三态 True/False/None，永不 raise）；None = 纯 CV（VL 触点按"vl disabled"
留痕，规则结果生效）。E5 成图（compose_group）在 compose.py。
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from .rec import _box_intersects, _parse_scale_text
from .vl import unit_ink_mask

DASH_LIKE = {"一", "—", "–", "-", "―", "~", "～"}
# R1 视图救援：小尺寸圆形/封闭视图被 OCR 误读的常见字符
O_FACTOR = {"O", "o", "0", "口", "D", "Q", "〇", "○", "Ο", "ο", "Θ",
            "O.", "o.", "0.", "O:", "0:", "C", "c", "U", "u", "Â",
            "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
            "⊙", "¤", "ø", "Ø", "e", "6", "9", "b", "p", "d", "q"}


class AssemblyConfig:
    """E1–E4 规则参数（E5 成图参数不在此，见 compose.py）。

    取值与原型 ArcheaExtract 默认一致（159 图实测调参定稿）：
    row_auto_max 是远间隙行并自动上限——(auto_max, row_gap_max] 区间
    降级 VL 确认（合法 row 合并实测最大 gap=97，134 的 109 为唯一
    超限且为误并）。prefix_ext 沿 rec.DEFAULTS（尺行前缀搜索范围）。
    """

    def __init__(self, label_gap_max: int = 60, link_gap: int = 52,
                 stack_gap_max: int = 90, row_gap_max: int = 110,
                 row_auto_max: int = 97, stack_xov: float = 0.45,
                 row_yov: float = 0.45, evict_conf_floor: float = 0.7,
                 evict_conf_margin: float = 0.3, ink_corner_fix: bool = True,
                 stiff_evict: bool = True, prefix_ext: int = 150):
        self.label_gap_max = label_gap_max
        self.link_gap = link_gap
        self.stack_gap_max = stack_gap_max
        self.row_gap_max = row_gap_max
        self.row_auto_max = row_auto_max
        self.stack_xov = stack_xov
        self.row_yov = row_yov
        self.evict_conf_floor = evict_conf_floor
        self.evict_conf_margin = evict_conf_margin
        self.ink_corner_fix = ink_corner_fix
        self.stiff_evict = stiff_evict
        self.prefix_ext = prefix_ext


# ---------------------------------------------------------------------------
# 基础几何/掩膜工具
# ---------------------------------------------------------------------------
def bbox_gap(a, b):
    """两 bbox 的 (gx, gy) 空隙（不相交为正值，相交为 0）。"""
    gx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    gy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return gx, gy


def bbox_hov(a, b):
    """x 向重叠长度。"""
    return min(a[2], b[2]) - max(a[0], b[0])


def bbox_vov(a, b):
    """y 向重叠长度。"""
    return min(a[3], b[3]) - max(a[1], b[1])


def union_box(boxes):
    """bbox 列表 -> 并集 bbox。"""
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def ink_mask(binary, box, pad=2):
    """bbox 区域（外扩 pad）内的墨迹掩膜（bool，原图坐标系）。"""
    H, W = binary.shape[:2]
    x0 = max(0, int(box[0]) - pad)
    y0 = max(0, int(box[1]) - pad)
    x1 = min(W, int(box[2]) + 1 + pad)
    y1 = min(H, int(box[3]) + 1 + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    m = np.zeros_like(binary, dtype=bool)
    m[y0:y1, x0:x1] = binary[y0:y1, x0:x1] > 0
    return m


def ink_density(binary, box, pad=12):
    """bbox 外扩 pad 后的局部墨迹占比（0~1；binary 为空返回 None）。

    用途：区分"空白区断裂符"与"成片墨迹场内的斑点/装饰短线"（阈值
    0.10；不可用更大半径——窄缝断裂符的窗口会被邻接视图墨迹淹没）。
    """
    if binary is None:
        return None
    H, W = binary.shape[:2]
    x0 = max(0, int(box[0]) - pad)
    y0 = max(0, int(box[1]) - pad)
    x1 = min(W, int(box[2]) + 1 + pad)
    y1 = min(H, int(box[3]) + 1 + pad)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    sub = binary[y0:y1, x0:x1]
    return float(sub.mean()) if sub.size else 0.0


def paste_region(mask):
    """bool 掩膜 -> (bbox, sub_mask)（裁到掩膜紧致 bbox）。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None, None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    return [x0, y0, x1, y1], mask[y0:y1, x0:x1]


class UnionFind:
    """轻量并查集（视图分组用）。"""

    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _crop_img(bgr, box, pad=4):
    """bbox 裁片（E2.5 VL 读号用；与 VlArbiter._crop 同口径）。"""
    H, W = bgr.shape[:2]
    x0 = max(0, int(box[0]) - pad)
    y0 = max(0, int(box[1]) - pad)
    x1 = min(W, int(box[2]) + pad)
    y1 = min(H, int(box[3]) + pad)
    return bgr[y0:y1, x0:x1]


def _same_artifact(vl, bgr, box_a, box_b):
    """same_artifact 协议包装：vl=None（纯 CV）返回 (None, 'vl disabled')。"""
    if vl is None:
        return None, "vl disabled"
    return vl.same_artifact(bgr=bgr, box_a=box_a, box_b=box_b)


# ---------------------------------------------------------------------------
# E1 原子收集
# ---------------------------------------------------------------------------
def build_assembly(bgr, kept, rec, vl=None, cfg=None):
    """分割(kept)+识别(rec) -> 原子 dict（视图带轮廓/填充掩膜；小元素用
    bbox+墨迹）。R1 视图救援（VL 批量筛查）+ R2 嵌套碎片吸收（VL 确认
    较大碎片）在收集过程中完成。

    kept: seg.extract_contours 输出（[{"bbox", "area", "contour"}, ...]）；
    rec:  rec.ArcheaRec.recognize 输出（scales/serials/texts/figures/
          others/serial_set/stats）。
    """
    cfg = cfg or AssemblyConfig()
    r = rec
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = binary > 0

    # 轮廓索引：bbox tuple -> contour（figures/bars 的 bbox 与 kept 一致）
    by_box = {tuple(k["bbox"]): k for k in kept}

    def contour_of(box):
        return by_box.get(tuple(int(v) for v in box))

    def fill_mask(contour):
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [contour["contour"]], 1)
        return m > 0

    views = []
    for f in r["figures"]:
        c = contour_of(f["bbox"])
        views.append({
            "id": len(views), "bbox": list(f["bbox"]),
            "area": f["area"], "contour": c,
            "mask": fill_mask(c) if c else None,
            "label_nos": [], "label_ranks": [], "label_boxes": [],
        })
    # R1 视图救援：小尺寸圆形/封闭视图（fig 阈值之下）被 OCR 误读成
    # 'O'/'0'/'口' 或整体 unreadable 时，从 others 中回捞为独立视图。
    # 救援视图标记 rescued=True 供追溯；不与现有视图/比例尺重叠。
    rescued_views = []
    rescue_cands = []                             # (o, vm, vbox, contour)
    for o in r["others"]:
        ob = o["bbox"]
        w_ = ob[2] - ob[0]
        h_ = ob[3] - ob[1]
        txt = (o.get("text") or "").strip()
        big = max(w_, h_) >= 36 and min(w_, h_) >= 24
        if not big or o["reason"] not in ("text", "unreadable",
                                          "lowconf", "tiny"):
            continue
        if not ((txt in O_FACTOR) or o["reason"] == "unreadable"):
            continue
        if any(_box_intersects(ob, v["bbox"], 2) for v in views):
            continue
        if any(_box_intersects(ob, s.get("bar_bbox") or s["bbox"], 2)
               for s in r["scales"]):
            continue
        c = contour_of(ob)
        if c is not None:
            vm = fill_mask(c)
            vbox = list(c["bbox"])
        else:                                     # 无轮廓：bbox 内墨迹兜底
            vm = ink_mask(binary, ob, pad=1)
            if vm is None or vm.sum() < 200:
                continue
            vbox = list(ob)
        rescue_cands.append((o, vm, vbox, c))
    # E1 救援判定 VL 化：候选批量送 VL 筛查"是否器物视图"，滤掉 O 形
    # 符号/装饰圈/图内杂符等假候选。三态语义：True 采纳 / False 弃 /
    # None（批调用或解析失败）维持规则结果——VL 不可用时按规则候选
    # 全部采纳，不阻塞主流程。
    if rescue_cands and vl is not None:
        flags, _note = vl.judge_views(
            bgr=bgr, units=[{"bbox": cnd[2]} for cnd in rescue_cands],
            context=f"R1 n={len(rescue_cands)}")
        if flags is not None:
            rescue_cands = [cnd for cnd, f in zip(rescue_cands, flags)
                            if f is not False]
    for o, vm, vbox, c in rescue_cands:
        views.append({
            "id": len(views), "bbox": vbox,
            "area": round(float(vm.sum()), 1), "contour": c,
            "mask": vm, "label_nos": [], "label_ranks": [],
            "label_boxes": [],
            "rescued": True,
        })
        rescued_views.append({"bbox": vbox, "reason": o["reason"],
                              "text": txt})
    # 正文序号 / 比例尺前缀序号分开；刻度式"序号"（细高 + 含破折号，如
    # '1—'/'1—1'，实为视图连接竖线被 OCR 误读）转作连接符证据，不作标号
    labels, prefixes, tick_links = [], [], []

    # 比例尺左侧序号（业务规则 K1 例外位）：与某比例尺 bbox 同 y 带且
    # 紧邻其左侧的序号是尺带标注，不是器物视图序号——归入 prefixes 供
    # E4 L1 前缀硬匹配使用，不再与器物序号竞争绑定
    def _scale_side(sb):
        cy_ = (sb[1] + sb[3]) / 2
        for sc_ in r["scales"]:
            tb = sc_["bbox"]
            if tb[1] - 6 <= cy_ <= tb[3] + 6 and 0 <= tb[0] - sb[2] <= 40:
                return True
        return False

    for s in r["serials"]:
        sb = s["bbox"]
        w_ = sb[2] - sb[0]
        h_ = sb[3] - sb[1]
        thin_tall = h_ >= 2.2 * max(w_, 1) and w_ <= 14 and h_ >= 15
        if thin_tall and re.search(r"[—–\-~～]", s["text"]):
            tick_links.append({"bbox": sb, "reason": "serial_tick",
                               "text": s["text"]})
            continue
        if not s.get("scale_prefix") and _scale_side(sb):
            s = dict(s)
            s["scale_prefix"] = True
            s["scale_side"] = True               # K1 例外位注记
        (prefixes if s.get("scale_prefix") else labels).append(s)
    # 连接符候选：connector 类 + 破折形文本 + 细长小组件；"视图内部装饰
    # 短线"须墨迹级确认（R5）：仅局部墨迹密度 >= 0.10（器物墨迹包围）才
    # 判装饰线——落在 bbox 空白区的断裂符不得按 bbox 包含误删
    links = []
    for o in r["others"]:
        ob, reason, txt = o["bbox"], o["reason"], (o.get("text") or "").strip()
        w_ = ob[2] - ob[0]
        h_ = ob[3] - ob[1]
        thin = (h_ >= 2.2 * max(w_, 1)) or (w_ >= 2.2 * max(h_, 1))
        cont = [v for v in views if v["bbox"][0] <= ob[0]
                and ob[2] <= v["bbox"][2] and v["bbox"][1] <= ob[1]
                and ob[3] <= v["bbox"][3]]
        if cont and ink_density(binary, ob, pad=12) >= 0.10:
            continue                  # 成片墨迹场内的斑点/装饰短线（R5）
        if reason == "connector" or (reason in ("text", "fig_zone")
                                     and txt in DASH_LIKE) \
                or (reason in ("text", "unreadable", "sliver") and thin
                    and max(w_, h_) <= 60):
            links.append({"bbox": ob, "reason": reason, "text": txt})
    # 'i'/'l' 误读救援：视图下方孤立小 'i'/'l' 多为印刷数字 1 的误读
    for o in r["others"]:
        ob, reason, txt = o["bbox"], o["reason"], (o.get("text") or "").strip()
        if reason == "text" and txt in ("i", "l") \
                and 10 <= ob[3] - ob[1] <= 30:
            labels.append({"bbox": ob, "text": "1", "no": "1",
                           "conf": o.get("conf", 0.5), "rotated": False,
                           "scale_prefix": False, "rescued": True})
    scales = [dict(s) for s in r["scales"]]
    # 嵌套碎片吸收：完全落入更大视图内部、且面积远小的小视图是器内笔画/
    # 剖面碎片，不是独立器物——并入外层视图。R2 收紧：bbox 包含之外还须
    # "掩膜级真实包含"（碎片填充区 >=60% 落在宿主填充区膨胀 9px 内）。
    drop = set()
    fragments = {}
    absorbed_events = []   # 吸收事件留痕（宿主旧id+碎片bbox/面积）
    for a in views:
        ab = a["bbox"]
        aa = (ab[2] - ab[0]) * (ab[3] - ab[1])
        for b in views:
            if a["id"] == b["id"]:
                continue
            bb = b["bbox"]
            if not (bb[0] <= ab[0] + 2 and ab[2] <= bb[2] - 2
                    and bb[1] <= ab[1] + 2 and ab[3] <= bb[3] - 2
                    and aa <= 0.25 * (bb[2] - bb[0]) * (bb[3] - bb[1])):
                continue
            am, bm = a.get("mask"), b.get("mask")
            if am is not None and bm is not None and am.any():
                aw, ah = ab[2] - ab[0], ab[3] - ab[1]
                if max(aw, ah) >= 8 * min(aw, ah):
                    # 细长条（笔画残段/中缝墨线）直接吸收——其位于器物
                    # 双线夹缝内，轮廓常未闭合而填不出该区域
                    pass
                else:
                    # 掩膜级真实包含：碎片墨迹 >=60% 落在宿主掩膜膨胀 9px
                    # 的范围内（紧贴宿主笔画的器内细部才算碎片）
                    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19))
                    bm_d = cv2.dilate(bm.astype(np.uint8), k) > 0
                    inter = int((am & bm_d).sum())
                    if inter < 0.6 * int(am.sum()):
                        continue                  # 掩膜不接触：并排视图，保留
            # E1 吸收判定 VL 化：仅对"真有歧义"的吸收对确认——掩膜验证
            # 通过且碎片面积占宿主 >5%。细长条豁免路径与微小碎片（<5%）
            # 规则置信充分，直接按规则吸收；VL 拒绝则保留为独立视图。
            if vl is not None:
                aa_host = (bb[2] - bb[0]) * (bb[3] - bb[1])
                aa_frag = (ab[2] - ab[0]) * (ab[3] - ab[1])
                if aa_frag > 0.05 * aa_host:
                    is_frag, _note = vl.confirm_absorption(
                        bgr=bgr, host_box=bb, frag_box=ab)
                    if is_frag is False:
                        continue
            absorbed_events.append({"host_old": b["id"],
                                    "frag_bbox": list(ab),
                                    "frag_area": round(float(am.sum()), 1)
                                    if am is not None else None})
            drop.add(a["id"])
            fragments.setdefault(b["id"], []).append(a["id"])
            break
    if drop:
        remap = {}
        new_views = []
        for v in views:
            if v["id"] in drop:
                continue
            remap[v["id"]] = len(new_views)
            new_views.append(v)
        for v in new_views:                        # 重编 id（全局以 id=索引）
            v["id"] = remap[v["id"]]
        fragments = {remap[k]: v
                     for k, v in fragments.items() if k in remap}
        absorbed_events = [{"host": remap.get(e["host_old"]),
                            "frag_bbox": e["frag_bbox"],
                            "frag_area": e["frag_area"]}
                           for e in absorbed_events]
        views = new_views
    return {"bgr": bgr, "binary": binary, "rec": r, "views": views,
            "labels": labels, "prefixes": prefixes,
            "links": links + tick_links,
            "scales": scales, "others": r["others"],
            "absorbed_fragments": fragments,
            "absorbed_events": absorbed_events,
            "rescued_views": rescued_views}


# ---------------------------------------------------------------------------
# E1.5 VL 二次判定：候选漏斗 -> judge_views -> 三态合并
# ---------------------------------------------------------------------------
def vl_review(at, vl):
    """对规则证据冲突的候选单元做 VL is_view 仲裁（返回 alarms 列表）。

    送 VL 的两类触发（其余单元不送，候选率 <15%）：
      duplicate_serial   others 中读出与已绑定序号同值的数字；
      big_digit_lowconf  lowconf 且读值为数字、maxdim>45。
    规则直判不送 VL：裸条元（长宽比>3.5 且墨迹面积<300px²）。报警不
    自动判：小圆读值 '0'/'8'（round_serial_ambiguous）转人工。

    三态合并：True -> 回捞为视图（rescued_vl=True，墨迹掩膜，参与
    E2~E5）；False -> 维持 others；None -> 维持 + 报警
    vl_verdict_unresolved。判定明细写入 at["vl_review"]，报警写入
    at["alarms_e15"] 并返回。
    """
    bgr = at["bgr"]
    binary = at["binary"]
    labels, others, views = at["labels"], at["others"], at["views"]
    alarms, review = [], []
    label_nos = {(s.get("no") or "").strip() for s in labels
                 if (s.get("no") or "").strip().isdigit()}
    if vl is not None and others:

        def _bare_bar(ob):
            """裸条元：极端长宽比且墨迹包围盒面积小（连接符/断裂符）。"""
            w_, h_ = ob[2] - ob[0], ob[3] - ob[1]
            thin = (h_ >= 3.5 * max(w_, 1)) or (w_ >= 3.5 * max(h_, 1))
            return thin and w_ * h_ < 300

        cands, cand_pairs = [], []
        for oi, o in enumerate(others):
            ob, reason = o["bbox"], o["reason"]
            txt = (o.get("text") or "").strip()
            if _bare_bar(ob):
                continue                        # 裸条直判：不消耗 VL
            m = re.search(r"\d{1,2}", txt)
            digit = m.group(0) if m else ""
            if not digit:
                continue
            # 尺寸下限：maxdim<12 的字形碎片不具备回捞意义
            w_, h_ = ob[2] - ob[0], ob[3] - ob[1]
            if max(w_, h_) < 12:
                continue
            # 破折号+数字 debris（'1-1'/'—1'）：不送 VL、不回捞
            if re.fullmatch(r"[\d\s\-–—~∼.·lI]+", txt) \
                    and re.search(r"[\-–—~∼]", txt):
                continue
            # 题注行（图注"1、瓷碗 2、银簪…"被 OCR 逐段读出）：不送 VL
            if re.match(r"^\d{1,2}\s*[、.．,，：:]", txt) \
                    and re.search("[\\u4e00-\\u9fff]", txt):
                continue

            # 细长杆歧义：竖直虚线段、断裂线、尺边被 OCR 拼成数字读值。
            # 纯形状无法区分"手绘细长杆（真部件）"与"虚线 debris"，
            # 不自动回捞也不静默丢弃，报警转人工。
            def _all_bar_like(box_):
                """细长杆判据：单元 bbox 细长（>=3），或所有有效组件的
                minAreaRect 细长（>=3，覆盖多段短虚线拼成的单元）。"""
                w_, h_ = box_[2] - box_[0], box_[3] - box_[1]
                if min(w_, h_) * 3.0 <= max(w_, h_):
                    return True
                m = unit_ink_mask(binary, box_)
                n, lab, stats, _ = cv2.connectedComponentsWithStats(
                    m.astype(np.uint8), connectivity=8)
                comps = 0
                for i in range(1, n):
                    if stats[i, 4] < 20:               # 噪点忽略
                        continue
                    comps += 1
                    ys, xs = np.nonzero(lab == i)
                    (_rcx, _rcy), (rw, rh), _ = cv2.minAreaRect(
                        np.column_stack([xs, ys]).astype(np.float32))
                    lo, hi = sorted((max(rw, 0.1), max(rh, 0.1)))
                    if hi < 3.0 * lo:
                        return False                   # 存在粗壮组件
                return comps > 0

            if _all_bar_like(ob):
                alarms.append({
                    "code": "slender_debris_ambiguous",
                    "msg": f"⚠ 报警：细长杆状单元{list(ob)} 读值{txt!r}"
                           f"（虚线段/断裂线/簪针杆无法自动区分），"
                           f"维持原分类待人工复核",
                    "bbox": list(ob)})
                continue
            w_, h_ = ob[2] - ob[0], ob[3] - ob[1]
            if reason == "lowconf" and max(w_, h_) > 45:
                cands.append({"bbox": list(ob), "src": "big_digit_lowconf",
                              "reason": reason, "text": txt})
                cand_pairs.append(oi)
            elif digit in label_nos and reason != "scale_zone" \
                    and max(w_, h_) >= 24:
                # duplicate_serial 仅收"大单元"（下限 24 与 R1 一致）
                cands.append({"bbox": list(ob), "src": "duplicate_serial",
                              "reason": reason, "text": txt, "no": digit})
                cand_pairs.append(oi)
        if cands:
            flags, _note = vl.judge_views(
                bgr=bgr, units=cands, context=f"E1.5 n={len(cands)}")
            drop = set()
            for oi, cnd, f in zip(cand_pairs, cands, flags):
                verdict = {"bbox": cnd["bbox"], "src": cnd["src"],
                           "reason": cnd["reason"], "text": cnd["text"],
                           "verdict": f}
                if f is True:
                    # 回捞为视图：墨迹掩膜（E5 compose 按掩膜粘贴原图像素）
                    mask = unit_ink_mask(binary, cnd["bbox"])
                    if mask.any():
                        views.append({
                            "id": len(views), "bbox": list(cnd["bbox"]),
                            "area": round(float(mask.sum()), 1),
                            "contour": None, "mask": mask,
                            "label_nos": [], "label_ranks": [],
                            "label_boxes": [], "rescued": True,
                            "rescued_vl": True})
                        at["rescued_views"].append(
                            {"bbox": list(cnd["bbox"]),
                             "reason": cnd["src"], "text": cnd["text"]})
                        drop.add(oi)
                        verdict["action"] = "rescued_view"
                    else:
                        verdict["action"] = "kept_other"
                elif f is False:
                    verdict["action"] = "kept_other"
                    if cnd["src"] == "big_digit_lowconf":
                        # VL 判否=放弃一个疑似视图单元：静默丢弃会把真器物
                        # 部件从视图集无声移除——显性化转人工复核
                        alarms.append({
                            "code": "view_candidate_rejected",
                            "msg": f"⚠ 报警：疑似视图单元{cnd['bbox']} 读值"
                                   f"{cnd['text']!r}（{cnd['src']}）VL 判否，"
                                   f"维持弃件处理，请复核是否为器物部件",
                            "bbox": list(cnd["bbox"])})
                else:
                    verdict["action"] = "alarm_unresolved"
                    alarms.append({
                        "code": "vl_verdict_unresolved",
                        "msg": f"⚠ 报警：单元{cnd['bbox']} 读值"
                               f"{cnd['text']!r}（{cnd['src']}）"
                               f"VL 判定不可用，维持原分类待复核",
                        "bbox": list(cnd["bbox"])})
                review.append(verdict)
            if drop:
                at["others"] = [o for oi, o in enumerate(others)
                                if oi not in drop]
    # 小圆 0/8 读值：不自动判，报警转人工（round_serial_ambiguous）
    reviewed = {tuple(c["bbox"]) for c in review}
    for o in at["others"]:
        ob = o["bbox"]
        if tuple(ob) in reviewed:
            continue
        txt = (o.get("text") or "").strip()
        dm = re.search(r"\d{1,2}", txt)
        if not dm or dm.group(0) not in ("0", "8"):
            continue
        w_, h_ = ob[2] - ob[0], ob[3] - ob[1]
        ar = min(w_, h_) / max(1, max(w_, h_))
        if (o["reason"] in ("text", "lowconf")
                and 0.7 <= ar <= 1.4 and 12 <= max(w_, h_) <= 45):
            alarms.append({
                "code": "round_serial_ambiguous",
                "msg": f"⚠ 报警：疑似圆形器物/数字{dm.group(0)!r}"
                       f"({list(ob)}) 无法自动区分，请人工复核",
                "bbox": list(ob)})
    at["vl_review"] = review
    at["alarms_e15"] = alarms
    return alarms


# ---------------------------------------------------------------------------
# E2 序号 -> 视图归属（外侧优先：下/上/右/左；内部兜底）
# ---------------------------------------------------------------------------
def bind_labels(at, cfg=None):
    """序号绑定视图：收集全部候选 -> 全局贪心分配 -> 内部候选让位。

    R3 全局贪心：视图被异号占据时序号自动迁移次优候选；同视图允许多个
    同号标号共存；内部候选（rank3）仅在最终该视图无外部标号时生效；
    左右侧候选 gap 上限收紧防相邻小视图抢号。
    R3b 刚性竞争置信度驱逐（stiff_evict）：低置信在位者被高置信挑战者
    取代（conf < evict_conf_floor 且挑战者 >= 在位者 + evict_conf_margin）。
    R3c 空白角墨迹纠正（ink_corner_fix）：bbox 空白角内的序号按二值墨迹
    换算为下侧外部关系（K2：序号不会印在视图上方，只换算 below）。
    R7 同号唯一（K1）：同一 no 多绑时按 (rank,conf) 择优留一。
    E2.1 连接符继承（始终执行）：断裂符"一端有号、一端无号"时无号视图
    继承该号（rank4，不作 G1 证据；分组仍由 E3 G2 完成）。

    绑定全过程留痕 at["e2"]（逐序号候选/归属/未绑定原因 + 指标）。
    """
    cfg = cfg or AssemblyConfig()
    views = at["views"]
    view_by_id = {v["id"]: v for v in views}
    REL_NAME = {0: "below", 1: "above", 2: "side", 3: "inside"}

    def _outside_gap_th(vb):
        return max(cfg.label_gap_max, 0.12 * max(vb[2] - vb[0],
                                                 vb[3] - vb[1]))

    def _inside(box, vb):
        return vb[0] <= box[0] and box[2] <= vb[2] \
            and vb[1] <= box[1] and box[3] <= vb[3]

    binary = at.get("binary")

    def _ink_rel(box, vb):
        """R3c 空白角纠正：bbox 内标号的墨迹级下/上关系换算。

        序号印在视图 bbox 的空白角（视觉位于器物下方，但 bbox 冗余把它
        包了进去）时，bbox 级判定只能给"内部"证据（rank3）。用二值墨迹
        做列向检查：标号所在列（±2px）上、剔除标号自身墨迹后，若墨迹仅
        存在于标号上方，则换算为下方外部关系（gap 以墨迹紧致边为基准）。
        K2：墨迹仅在标号下方（视觉在器物上方）不换算，返回 None。
        """
        if binary is None:
            return None
        H, W = binary.shape[:2]
        cx0 = max(0, int(box[0]) - 2)
        cx1 = min(W, int(box[2]) + 3)
        vy0 = max(0, int(vb[1]))
        vy1 = min(H, int(vb[3]) + 1)
        if cx1 <= cx0 or vy1 <= vy0:
            return None
        col = binary[vy0:vy1, cx0:cx1].copy()
        ly0 = max(0, int(box[1]) - 2 - vy0)      # 剔除标号自身墨迹（含余量）
        ly1 = min(col.shape[0], int(box[3]) + 3 - vy0)
        if ly1 > ly0:
            col[ly0:ly1, :] = False
        ys, _xs = np.nonzero(col)
        if len(ys) == 0:
            return None
        gap_th = _outside_gap_th(vb)
        below = ys[ys > int(box[3]) + 2 - vy0]   # 标号下方的视图墨迹
        above = ys[ys < int(box[1]) - 2 - vy0]   # 标号上方的视图墨迹
        if len(below) == 0 and len(above) > 0:
            gap = int(box[1]) - int(above.max() + vy0)   # 到墨迹紧致底的间隙
            if gap <= gap_th:
                return (0, gap)                  # 视觉在器物下方
        return None

    # 1) 逐 label 收集全部候选 (rank, gap, view_id)
    cands = {}
    above_rej = {}                        # id(lb) -> 曾有上方关系被拒（K2）
    trace = []                            # E2 留痕（与 at["labels"] 对齐）
    # 同号最高置信（R3c 重复守卫用）：图内每序号通常只印一次（K1）
    no_best_conf = {}
    for lb0 in at["labels"]:
        no0 = (lb0.get("no") or "").strip()
        if no0.isdigit():
            no_best_conf[no0] = max(no_best_conf.get(no0, 0.0),
                                    lb0.get("conf") or 0.0)
    for li, lb in enumerate(at["labels"]):
        box = lb["bbox"]
        item = {"idx": li, "bbox": list(box),
                "no": (lb.get("no") or "").strip(),
                "text": lb.get("text", ""), "conf": lb.get("conf"),
                "candidates": [], "stiff": False,
                "status": "assigned", "attach": None,
                "rank": None, "rel": None, "gap": None,
                "conflict_view": None, "above_rejected": False}
        trace.append(item)
        if (box[3] - box[1]) < 10 or (box[2] - box[0]) < 3 \
                or not (lb.get("no") or "").strip().isdigit():
            lb["_attach"] = None
            item["status"] = "invalid"
            continue
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        got = []
        for v in views:
            vb = v["bbox"]
            rel = None
            if cy >= vb[3] - 8 and \
                    vb[0] - 0.15 * (vb[2] - vb[0]) <= cx <= vb[2] + 0.15 * (vb[2] - vb[0]):
                # 正下方（最常见，K2 标准位）：以序号中心 cy 是否到达视图
                # 下缘附近判定（兼容骑跨下缘的印刷位）；gap<0 时要求 x 向
                # 实际交叠（序号整体位于视图 x 范围之外者不属此视图）
                if box[1] < vb[3] and \
                        (box[2] < vb[0] - 2 or box[0] > vb[2] + 2):
                    continue
                rel = (0, box[1] - vb[3])
            elif box[3] <= vb[1] + 8 and \
                    vb[0] - 0.15 * (vb[2] - vb[0]) <= cx <= vb[2] + 0.15 * (vb[2] - vb[0]):
                # K2 业务规则：器物序号印在视图下侧，不会在上方——上方
                # 关系不生成候选。该序号仍可作为其上方视图的"正下方"
                # 候选参与绑定；若全图再无其它候选则走"无候选"留痕报警
                above_rej[id(lb)] = True
                continue
            elif box[0] >= vb[2] - 8 and \
                    vb[1] - 0.15 * (vb[3] - vb[1]) <= cy <= vb[3] + 0.15 * (vb[3] - vb[1]):
                rel = (2, box[0] - vb[2])             # 右侧（gap 上限收紧）
            elif box[2] <= vb[0] + 8 and \
                    vb[1] - 0.15 * (vb[3] - vb[1]) <= cy <= vb[3] + 0.15 * (vb[3] - vb[1]):
                rel = (2, vb[0] - box[2])             # 左侧（gap 上限收紧）
            elif _inside(box, vb):
                rel = None
                if cfg.ink_corner_fix:
                    # R3c 重复守卫：同号存在更高置信者（低置信重复）不做
                    # 换算——维持 rank3 内部兜底（不参与 G1 同号分组）
                    no_s = (lb.get("no") or "").strip()
                    dup = (no_best_conf.get(no_s, 0.0)
                           > (lb.get("conf") or 0.0) + 1e-6)
                    rel = None if dup else _ink_rel(box, vb)
                if rel is None:
                    rel = (3, 0)          # 视图内部（兜底；空白角纠正 R3c）
            if rel is None:
                continue
            if rel[0] == 3:
                got.append((3, 0, v["id"]))
                continue
            gap_th = _outside_gap_th(vb)
            if rel[0] == 2:                           # 左右：防相邻小视图抢号
                gap_th = min(gap_th, max(30, 0.1 * max(vb[2] - vb[0],
                                                       vb[3] - vb[1])))
            if rel[1] <= gap_th:                      # 负 gap = 序号贴入视图 bbox，合法
                got.append((rel[0], rel[1], v["id"]))
        got.sort(key=lambda t: (t[0], t[1]))
        cands[id(lb)] = got
        item["candidates"] = [{"view": vid, "rank": r,
                               "rel": REL_NAME[r], "gap": int(g)}
                              for r, g, vid in got]
        item["stiff"] = len(got) == 1
        item["above_rejected"] = bool(above_rej.get(id(lb)))

    # 2) 全局贪心分配：先"刚性"label（仅一个候选视图，无从让位），后
    # "弹性"label 按 (rank, gap) 升序；视图被异号占据时弹性 label 自动
    # 迁移次优候选
    lbs_by_id = {id(lb): lb for lb in at["labels"]}
    assign = {}                       # id(lb) -> (view_id, rank, gap)
    view_labels = {}                  # view_id -> [lb,...]
    all_pairs = sorted(((rank, gap, lid, vid)
                        for lid, cs in cands.items()
                        for (rank, gap, vid) in cs),
                       key=lambda t: (t[0], t[1]))
    stiff = [p for p in all_pairs if len(cands[p[2]]) == 1]
    flex = [p for p in all_pairs if len(cands[p[2]]) > 1]

    def _place(pairs, allow_evict=False):
        evicted = []
        for rank, gap, lid, vid in pairs:
            if lid in assign:
                continue
            no = (lbs_by_id[lid].get("no") or "").strip()
            existing = view_labels.get(vid, [])
            blockers = [l for l in existing
                        if (l.get("no") or "").strip() != no]
            if blockers:
                # R3b 置信度驱逐：仅刚性标号（无次优候选可迁移）触发
                if not (allow_evict and cfg.stiff_evict):
                    continue
                inc = blockers[0]
                inc_conf = inc.get("conf") or 0.0
                cur_conf = lbs_by_id[lid].get("conf") or 0.0
                if not (inc_conf < cfg.evict_conf_floor
                        and cur_conf >= inc_conf + cfg.evict_conf_margin):
                    continue
                assign.pop(id(inc), None)
                view_labels[vid].remove(inc)
                inc["_evicted_by_conf"] = True
                evicted.append(inc)
            assign[lid] = (vid, rank, gap)
            view_labels.setdefault(vid, []).append(lbs_by_id[lid])
        return evicted

    evicted_all = _place(stiff, allow_evict=True)
    _place(flex)

    # 3) 内部候选让位：视图同时有外部+内部标号时，内部弃用
    inner_yielded = []
    for vid, lbs in list(view_labels.items()):
        vb = view_by_id[vid]["bbox"]
        outs = [l for l in lbs if not _inside(l["bbox"], vb)]
        ins = [l for l in lbs if _inside(l["bbox"], vb)]
        if outs and ins:
            for l in ins:
                assign.pop(id(l), None)
                view_labels[vid].remove(l)
                inner_yielded.append(l)

    # 3.5) R7 同号唯一（K1：例外位"比例尺左侧"已由 E1 归入 prefixes）：
    # 同一 no 有多个 serial 获绑定时按 (rank, conf) 择优保留一个。多视图
    # 共享序号走 E2.1 断裂符继承（rank4，不在本步约束范围）。
    uniq_dropped = []
    by_no_assigned = {}
    for lid, (vid, rank, gap) in assign.items():
        no = (lbs_by_id[lid].get("no") or "").strip()
        by_no_assigned.setdefault(no, []).append(
            (rank, lbs_by_id[lid].get("conf") or 0.0, lid))
    for no, lst in by_no_assigned.items():
        if len(lst) <= 1:
            continue
        lst.sort(key=lambda t: (t[0], -t[1]))
        for rank_, _conf, lid in lst[1:]:
            vid = assign.pop(lid, (None, None, None))[0]
            lb = lbs_by_id[lid]
            if vid is not None and lb in view_labels.get(vid, []):
                view_labels[vid].remove(lb)
            lb["_dropped_by_uniqueness"] = True
            uniq_dropped.append(lb)

    # 4) 落盘：视图挂标号；未分配的区分记录（冲突弃用/内部让位/远置）
    for v in views:
        v["label_nos"] = []
        v["label_ranks"] = []
        v["label_boxes"] = []
        v["label_idx"] = []
    for li, lb in enumerate(at["labels"]):
        item = trace[li]
        if item["status"] == "invalid":
            continue
        got = assign.get(id(lb))
        if got is None:
            lb["_attach"] = None
            if lb in uniq_dropped:
                item["status"] = "uniqueness_dropped"
            elif lb in inner_yielded:
                lb["_inner_yielded"] = True
                item["status"] = "inner_yielded"
            elif cands.get(id(lb)):
                lb["_conflict_dropped"] = cands[id(lb)][0][2]
                item["status"] = "conflict_dropped"
                item["conflict_view"] = cands[id(lb)][0][2]
                item["evicted"] = bool(lb.get("_evicted_by_conf"))
            else:
                item["status"] = "no_candidate"
            continue                # 无候选：图注行等远置标号，弃用
        vid, rank, _gap = got
        lb["_attach"] = vid
        no = (lb.get("no") or "").strip()
        view_by_id[vid]["label_nos"].append(no)
        view_by_id[vid]["label_ranks"].append(rank)
        view_by_id[vid]["label_boxes"].append(lb["bbox"])
        view_by_id[vid]["label_idx"].append(li)
        item["attach"] = vid
        item["rank"] = rank
        item["rel"] = REL_NAME.get(rank)
        item["gap"] = int(_gap)
        item["status"] = "assigned"

    # 5) E2.1 连接符继承（始终执行）：断裂符两端"一端有号、一端无号"时，
    #    无号视图继承有号视图的序号。关联几何与 E3 G2 同源（横/竖向、
    #    轴向对齐 ±8、端向 gap ∈ [-8, link_gap]），同侧多匹配取最近者。
    direct = {v["id"]: list(v["label_nos"]) for v in views}  # 直接绑定快照
    # 来源守卫：只认外部证据（rank<3）的直接绑定号——rank3 内部号多为
    # 拓片纹理 OCR 幻影，经连接符传播会把幻影挂到更多视图
    src_ext = {}
    for v in views:
        src_ext[v["id"]] = list(dict.fromkeys(
            no for no, rk in zip(v["label_nos"], v["label_ranks"])
            if rk < 3))
    got = set()                                   # 已继承视图（一次）
    link_trace = []
    n_inherited = 0
    for lk in at.get("links", []):
        b = lk["bbox"]
        A, B = _resolve_link_ends(views, b, binary, cfg)
        rec = {"bbox": list(b), "text": lk.get("text"),
               "reason": lk.get("reason"),
               "vertical": (b[3] - b[1]) >= (b[2] - b[0]),
               "ends": {"a": A, "b": B}}
        if not A or not B:
            rec["cls"] = "unmatched"
        elif A[0] == B[0]:
            rec["cls"] = "self_loop"
        else:
            na, nb = direct[A[0]], direct[B[0]]
            if na and nb:
                rec["cls"] = ("both_labeled_same"
                              if set(na) & set(nb)
                              else "both_labeled_cross")
            elif na or nb:
                src_id, dst_id = (A[0], B[0]) if na else (B[0], A[0])
                if dst_id in got:
                    rec["cls"] = "dst_already_inherited"
                elif not src_ext[src_id]:
                    # 来源视图只有内部绑定号（幻影高发），不继承
                    rec["cls"] = "src_inside_only"
                else:
                    nos = list(dict.fromkeys(src_ext[src_id]))
                    dst = view_by_id[dst_id]
                    dst["label_nos"].extend(nos)
                    dst["label_ranks"].extend([4] * len(nos))
                    dst.setdefault("label_inherited", {})[
                        ",".join(nos)] = {
                            "from_view": src_id, "link_bbox": list(b)}
                    got.add(dst_id)
                    n_inherited += len(nos)
                    rec["cls"] = "inherited"
                    rec["inherit"] = {"to_view": dst_id,
                                      "from_view": src_id, "nos": nos}
            else:
                rec["cls"] = "both_unlabeled"
        link_trace.append(rec)

    # 继承号语义（结构性约定）：v["label_ranks"] 记 4——G1 同号分组只认
    # 外部证据（rank<3），继承号不作同号证据；不写 v["label_boxes"]。

    # 6) E2 留痕：逐视图绑定 + 指标（判定不变，仅记录）
    def _numkey(s):
        return (0, int(s)) if s.isdigit() else (1, s)

    nos_bound = {}
    for vid, ids in direct.items():               # 仅直接绑定（不含继承）
        for no in ids:
            nos_bound.setdefault(no, set()).add(vid)
    serial_set = (at.get("rec") or {}).get("serial_set") or {}
    set_nums = {str(x) for x in serial_set.get("nums", [])}
    # 救援序号并入序号集口径：'i'/'l'→'1' / E2.5 VL 补读的序号不在
    # rec.serial_set 里，否则会产生假"绑定号不在序号集"报告
    rescued_nos = {(lb.get("no") or "").strip() for lb in at["labels"]
                   if (lb.get("rescued") or lb.get("_vl_rescued"))
                   and (lb.get("no") or "").strip().isdigit()}
    set_nums |= rescued_nos
    valid = [t for t in trace if t["status"] != "invalid"]
    assigned = [t for t in valid if t["status"] == "assigned"]
    rank_hist = {}
    for t in assigned:
        rank_hist[t["rel"]] = rank_hist.get(t["rel"], 0) + 1
    metrics = {
        "n_labels": len(trace),
        "n_valid": len(valid),
        "n_assigned": len(assigned),
        "n_no_candidate": sum(1 for t in valid
                              if t["status"] == "no_candidate"),
        "n_conflict_dropped": sum(1 for t in valid
                                  if t["status"] == "conflict_dropped"),
        "n_uniqueness_dropped": sum(1 for t in valid
                                    if t["status"] == "uniqueness_dropped"),
        "n_above_rejected": sum(1 for t in trace
                                if t.get("above_rejected")),
        "n_evicted": sum(1 for t in valid if t.get("evicted")),
        "n_inner_yielded": sum(1 for t in valid
                               if t["status"] == "inner_yielded"),
        "assign_rate": (round(len(assigned) / len(valid), 4)
                        if valid else None),
        "rank_hist": rank_hist,
        "n_views": len(views),
        "n_views_labeled": sum(1 for ids in direct.values() if ids),
        "n_views_unlabeled": sum(1 for ids in direct.values() if not ids),
        "n_inherited": n_inherited,
        "n_inherited_views": len(got),
        "n_views_labeled_after": sum(1 for v in views if v["label_nos"]),
        "n_views_unlabeled_after": sum(1 for v in views
                                       if not v["label_nos"]),
        "nos_bound": {k: sorted(v2) for k, v2 in sorted(nos_bound.items(),
                                                        key=lambda kv: _numkey(kv[0]))},
        "n_multi_view_no": sum(1 for v2 in nos_bound.values() if len(v2) > 1),
        "serial_set_nums": sorted(set_nums, key=_numkey),
        "set_nums_unbound": sorted(set_nums - set(nos_bound), key=_numkey),
        "bound_nos_not_in_set": sorted(set(nos_bound) - set_nums,
                                       key=_numkey),
    }
    at["e2"] = {
        "params": {"label_gap_max": cfg.label_gap_max,
                   "side_gap_cap": "max(30, 0.1*maxdim)",
                   "inner_yields_to_outside": True,
                   "ink_corner_fix": cfg.ink_corner_fix,
                   "stiff_evict": cfg.stiff_evict,
                   "evict_conf_floor": cfg.evict_conf_floor,
                   "evict_conf_margin": cfg.evict_conf_margin,
                   "link_inherit": "always-on (E2.1, rank4 evidence)",
                   "greedy": "stiff-first(evict-able) then (rank,gap) flex",
                   "above_candidates": "rejected (K2: 器物序号只在视图下侧)",
                   "serial_unique": "R7: 同号多绑按 (rank,conf) 择优留一 (K1)",
                   "scale_side_serials": "routed to prefixes (K1 例外位)"},
        "labels": trace,
        "links": link_trace,
        "metrics": metrics,
    }
    return evicted_all


# ---------------------------------------------------------------------------
# 连接符端点解析（E2.1 继承与 E3 G2 共用）
# ---------------------------------------------------------------------------
def _resolve_link_ends(views, b, binary=None, cfg=None):
    """断裂符 bbox -> (上/左端视图, 下/右端视图) 各至多一个。

    候选收集（G2 原窗口 + 端点包含）：轴向对齐 ±8、端向 gap ∈
    [-8, link_gap]；或视图 bbox 在关联轴上包含该端点。多候选解析
    （墨迹级）：端向墨迹距离最近者；带内无墨迹退回 bbox |gap|；
    距离并列取不包含对方 bbox 的更"局部"视图。binary 为空时退回纯
    bbox |gap|。
    """
    cfg = cfg or AssemblyConfig()
    H = W = 0
    if binary is not None:
        H, W = binary.shape[:2]
    gap_max = cfg.link_gap
    vertical = (b[3] - b[1]) >= (b[2] - b[0])
    lo_end, hi_end = (b[1], b[3]) if vertical else (b[0], b[2])
    cands = {"a": [], "b": []}          # [(vid, contained_only)]
    for v in views:
        vb = v["bbox"]
        if vertical:
            if not (vb[0] - 8 <= (b[0] + b[2]) / 2 <= vb[2] + 8):
                continue
            c_a = (-8 <= lo_end - vb[3] <= gap_max)
            c_a_cont = (vb[1] <= lo_end <= vb[3])
            c_b = (-8 <= vb[1] - hi_end <= gap_max)
            c_b_cont = (vb[1] <= hi_end <= vb[3])
        else:
            if not (vb[1] - 8 <= (b[1] + b[3]) / 2 <= vb[3] + 8):
                continue
            c_a = (-8 <= lo_end - vb[2] <= gap_max)
            c_a_cont = (vb[0] <= lo_end <= vb[2])
            c_b = (-8 <= vb[0] - hi_end <= gap_max)
            c_b_cont = (vb[0] <= hi_end <= vb[2])
        hit_a = c_a or c_a_cont
        hit_b = c_b or c_b_cont
        if hit_a:
            cands["a"].append((v["id"], c_a_cont and not c_a))
        if hit_b:
            cands["b"].append((v["id"], c_b_cont and not c_b))

    v_by_id = {v["id"]: v for v in views}

    def _edge_gap(vid, end):
        vb = v_by_id[vid]["bbox"]
        if vertical:
            return (lo_end - vb[3]) if end == "a" else (vb[1] - hi_end)
        return (lo_end - vb[2]) if end == "a" else (vb[0] - hi_end)

    def _ink_dist(vid, end):
        """端向墨迹距离（px）：错误一侧/带内无墨迹返回 None。"""
        if binary is None:
            return None
        vb = v_by_id[vid]["bbox"]
        if vertical:
            x0, x1 = max(0, int(b[0])), min(W, int(b[2]) + 1)
            y0, y1 = max(0, int(vb[1])), min(H, int(vb[3]) + 1)
            sub = binary[y0:y1, x0:x1]
            cx0, cx1 = max(0, int(b[0]) - x0), min(x1 - x0, int(b[2]) + 1 - x0)
        else:
            y0, y1 = max(0, int(b[1])), min(H, int(b[3]) + 1)
            x0, x1 = max(0, int(vb[0])), min(W, int(vb[2]) + 1)
            sub = binary[y0:y1, x0:x1]
            cx0, cx1 = max(0, int(b[0]) - x0), min(x1 - x0, int(b[2]) + 1 - x0)
        if cx1 > cx0:
            sub = sub.copy()
            sub[:, cx0:cx1] = False          # 排除连接符自身墨迹
        idx = np.nonzero(sub.any(axis=1 if vertical else 0))[0]
        if idx.size == 0:
            return None
        if vertical:
            edge = y0 + (idx.max() if end == "a" else idx.min())
        else:
            edge = x0 + (idx.max() if end == "a" else idx.min())
        d = (lo_end - edge) if end == "a" else (edge - hi_end)
        return d if d >= 0 else None         # 墨迹在错误一侧：不候选

    def _mask_ink_dist(vid, end):
        """包含型候选专用：视图自身掩膜在连接符带内的最近墨迹到端点的
        距离（侧向无关——包含型候选的墨迹环绕端点，方向无意义）。
        掩膜缺失返回 None。"""
        v = v_by_id[vid]
        m = v.get("mask")
        if m is None:
            return None
        if vertical:
            x0, x1 = max(0, int(b[0])), min(W, int(b[2]) + 1)
            band = m[:, x0:x1]
            pos = lo_end if end == "a" else hi_end
            idx = np.nonzero(band.any(axis=1))[0]
            if idx.size == 0:
                return None
            return int(min(abs(int(i) - pos) for i in idx))
        y0, y1 = max(0, int(b[1])), min(H, int(b[3]) + 1)
        band = m[y0:y1, :]
        pos = lo_end if end == "a" else hi_end
        idx = np.nonzero(band.any(axis=0))[0]
        if idx.size == 0:
            return None
        return int(min(abs(int(i) - pos) for i in idx))

    out = []
    for end in ("a", "b"):
        entries = cands[end]
        if not entries:
            out.append([])
            continue
        ids = [e[0] for e in entries]
        all_cont = all(f for _v, f in entries)
        if len(ids) == 1 and all_cont and binary is not None:
            # 唯一包含候选盲采否决：端点落在 bbox 内部且无窗口邻接候选
            # 时——校验其掩膜最近墨迹：距离 > link_gap 视为无证据，拒绝
            # （端空，宁缺勿错）。多候选端不否决：相对择优本就安全。
            d = _mask_ink_dist(ids[0], end)
            if d is not None and d > gap_max:
                out.append([])
                continue
            out.append(list(ids))
            continue
        if len(ids) > 1 and binary is not None:
            scored = []
            for vid in ids:
                d = _ink_dist(vid, end)
                scored.append((d if d is not None
                               else abs(_edge_gap(vid, end)) + 1e6,
                               vid))
            best = min(s for s, _ in scored)
            tied = [vid for s, vid in scored if s <= best + 1]
            if len(tied) > 1:
                def _contains(x, y):
                    bx, by = v_by_id[x]["bbox"], v_by_id[y]["bbox"]
                    return (bx[0] <= by[0] and by[2] <= bx[2]
                            and bx[1] <= by[1] and by[3] <= bx[3])
                tied = [vid for vid in tied
                        if not any(vid != o and _contains(vid, o)
                                   for o in tied)] or tied
            ids = [min(tied, key=lambda v_: (
                next(s for s, v2 in scored if v2 == v_), v_))]
        out.append(list(ids))
    return out[0], out[1]


def _extend_link_end(views, b, binary, exclude_ids, empty_end,
                     text="", cfg=None):
    """S4 连接符轴线延伸：单端已解析、另一端为空时，沿连接符主轴向空端
    延伸找对端视图。

    护栏：数字文本拒绝（1~2 位数字的"连接符"实为误判的印刷序号）；
    墨距上限 max(1.6*link_gap, 2.0*连接符长)。候选硬约束：主轴与视图
    bbox 相交（±8）、视图位于空端一侧、不与已解析端同组。择端：带内
    墨迹距离最近者（无墨迹证据不延伸）。返回 (view_id, 墨距) 或 None。
    """
    cfg = cfg or AssemblyConfig()
    H, W = binary.shape[:2]
    vertical = (b[3] - b[1]) >= (b[2] - b[0])
    lo_end, hi_end = (b[1], b[3]) if vertical else (b[0], b[2])
    conn_len = (b[3] - b[1]) if vertical else (b[2] - b[0])
    if text.isdigit() and len(text) <= 2:
        return None                          # 印刷序号数字误判为连接符
    d_cap = max(1.6 * cfg.link_gap, 2.0 * conn_len)
    best = None
    for v in views:
        if v["id"] in exclude_ids:
            continue
        vb = v["bbox"]
        if vb[0] <= b[0] and b[2] <= vb[2] \
                and vb[1] <= b[1] and b[3] <= vb[3]:
            continue      # 视图包含连接符：是"容器"不是延伸目标
        if vertical:
            if not (vb[0] - 8 <= (b[0] + b[2]) / 2 <= vb[2] + 8):
                continue                      # 主轴不与 bbox 相交
            if empty_end == "a":
                if vb[3] > lo_end + 8:
                    continue                  # 不在空端（上）一侧
            else:
                if vb[1] < hi_end - 8:
                    continue                  # 不在空端（下）一侧
        else:
            if not (vb[1] - 8 <= (b[1] + b[3]) / 2 <= vb[3] + 8):
                continue
            if empty_end == "a":
                if vb[2] > lo_end + 8:
                    continue
            else:
                if vb[0] < hi_end - 8:
                    continue
        # 带内墨迹距离（与 _resolve_link_ends._ink_dist 同口径）
        if vertical:
            x0, x1 = max(0, int(b[0])), min(W, int(b[2]) + 1)
            y0, y1 = max(0, int(vb[1])), min(H, int(vb[3]) + 1)
            sub = binary[y0:y1, x0:x1]
            cy0 = max(0, int(b[1]) - y0)
            cy1 = min(y1 - y0, int(b[3]) + 1 - y0)
            if cy1 > cy0:
                sub = sub.copy()
                sub[cy0:cy1, :] = False       # 排除连接符自身墨迹
            idx = np.nonzero(sub.any(axis=1))[0]
            if idx.size == 0:
                continue                      # 带内无墨迹：不候选
            edge = y0 + (idx.max() if empty_end == "a" else idx.min())
        else:
            y0, y1 = max(0, int(b[1])), min(H, int(b[3]) + 1)
            x0, x1 = max(0, int(vb[0])), min(W, int(vb[2]) + 1)
            sub = binary[y0:y1, x0:x1]
            cx0 = max(0, int(b[0]) - x0)
            cx1 = min(x1 - x0, int(b[2]) + 1 - x0)
            if cx1 > cx0:
                sub = sub.copy()
                sub[:, cx0:cx1] = False       # 排除连接符自身墨迹
            idx = np.nonzero(sub.any(axis=0))[0]
            if idx.size == 0:
                continue                      # 带内无墨迹：不候选
            edge = x0 + (idx.max() if empty_end == "a" else idx.min())
        d = (lo_end - edge) if empty_end == "a" else (edge - hi_end)
        if d < 0:
            continue                          # 墨迹在错误一侧
        if d > d_cap:
            continue                          # 超出延伸上限：证据不足
        if best is None or d < best[1]:
            best = (v["id"], int(d))
    return best


# ---------------------------------------------------------------------------
# E2.5 序号漏检 VL 补救：OCR 漏读的正文序号无法凭空找回，但其印刷体
# 单元往往仍在 others 里（lowconf/unreadable/tiny）。对"疑似序号形态 +
# 紧邻某视图"的此类单元批量裁片送 VL 复读，读出恰为缺失序号且可归位
# 相邻视图的，补挂绑定（rank2 外部证据）。
# ---------------------------------------------------------------------------
def rescue_missing_serials(at, vl):
    """返回补救成功的序号数。VL 禁用（vl=None）/无缺失/无候选时为 0。"""
    if vl is None:
        return 0
    views = at["views"]
    nums = set(at["rec"]["serial_set"].get("nums", []))
    bound = set()
    for v in views:
        bound.update(n for n in v["label_nos"] if n.isdigit())
    missing = {n for n in nums if n not in bound}
    if not missing:
        return 0
    used_boxes = ([lb["bbox"] for lb in at["labels"]]
                  + [x["bbox"] for x in at["prefixes"]]
                  + [s["bbox"] for s in at["scales"]])
    cands = []                                    # (unit, view_id, gap)
    for o in at["rec"]["others"]:
        ob = o["bbox"]
        w, h = ob[2] - ob[0], ob[3] - ob[1]
        if not (4 <= w <= 45 and 8 <= h <= 45):
            continue                              # 非序号形态
        if o["reason"] not in ("lowconf", "unreadable", "tiny"):
            continue
        if any(_box_intersects(ob, ub, 2) for ub in used_boxes):
            continue                              # 已被识别/占用
        if any(s.get("bar_bbox")
               and _box_intersects(ob, s["bar_bbox"], 2)
               for s in at["scales"]):
            continue                              # 尺上杂物不补
        best = None                               # 紧邻视图（序号距离）
        for v in views:
            vb = v["bbox"]
            cx, cy = (ob[0] + ob[2]) / 2, (ob[1] + ob[3]) / 2
            gap = None
            if ob[1] >= vb[3] - 8 and vb[0] - 20 <= cx <= vb[2] + 20:
                gap = ob[1] - vb[3]
            # K2 业务规则：序号不会在视图上方——rescue 不采上方关系
            elif ob[0] >= vb[2] - 8 and vb[1] - 20 <= cy <= vb[3] + 20:
                gap = ob[0] - vb[2]
            elif ob[2] <= vb[0] + 8 and vb[1] - 20 <= cy <= vb[3] + 20:
                gap = vb[0] - ob[2]
            if gap is not None and 0 <= gap <= 60 \
                    and (best is None or gap < best[1]):
                best = (v["id"], gap)
        if best is not None:
            cands.append((o, best[0]))
    if not cands:
        return 0
    crops = [_crop_img(at["bgr"], o["bbox"], pad=4) for o, _v in cands]
    reads, _note = vl.read_serials(
        crops=crops, context=f"missing={sorted(missing)}")
    if not reads:
        return 0
    fixed = 0
    for (o, vid), no in zip(cands, reads):
        no = (no or "").strip()
        if not (no.isdigit() and no in missing):
            continue
        v = views[vid]
        v["label_nos"].append(no)
        v["label_ranks"].append(2)                # 外部证据（相邻）
        v["label_boxes"].append(o["bbox"])
        at["labels"].append({"no": no, "bbox": list(o["bbox"]),
                             "text": no, "conf": o.get("conf", 0.5),
                             "rotated": False, "scale_prefix": False,
                             "_vl_rescued": True})
        missing.discard(no)
        fixed += 1
    return fixed


# ---------------------------------------------------------------------------
# E3 视图分组（G1 同号 > G2 连接符 > G3 无标号组迭代吸附 > G4 带号单例
# 吸附 > VL 兜底；S1 连通分量闸 / S2 完整视图守卫 / S4 轴线延伸穿插）
# ---------------------------------------------------------------------------
def group_views(at, vl=None, cfg=None):
    """并查集分组。返回 (groups: [[view_id,...]], merge_log)。

    G1 同序号视图必同组（仅外部绑定 rank<3 作证据）；G2 连接符（端点
    解析墨迹级择优 + S4 轴线延伸）；S1 规则B连通分量闸（无序号多物体
    图不强制配对）；G3 无标号组迭代吸附（浅相交/远间隙/守卫降级 VL）；
    G4 带号单例吸附紧邻无标号组；全图无序号 -> G0 全并（规则B）。
    VL 触点统计写入 at["e3_stats"]（无行为影响）。
    """
    cfg = cfg or AssemblyConfig()
    views = at["views"]
    n = len(views)
    uf = UnionFind(n)
    merge_log = []
    stats = {"merges": {}, "vl_touchpoints": 0, "g3_touch_shallow_vl": 0,
             "g3_touch_shallow_vl_merged": 0, "g3_touch_shallow_merge": 0,
             "g3_ambiguous": 0, "g3_vl_merged": 0, "g3_abandon": 0,
             # 远间隙行并降级 VL（row_auto_max < gap <= row_gap_max）留痕
             "g3_row_far_touchpoints": 0, "g3_row_far_vl_merged": 0,
             "g3_row_far_holds": 0,
             "g4_absorb": 0, "g4_ambiguous": 0, "g4_vl_merged": 0,
             "g4_abandon": 0,
             # S1 规则B连通分量闸 / S2 完整视图守卫 / S4 轴线延伸 留痕
             "s1_gate_fired": 0, "s1_gate_components": 0,
             "s2_guard_touchpoints": 0, "s2_guard_vl_merged": 0,
             "s2_guard_holds": 0,
             "s4_ext_attempt": 0, "s4_ext_merged": 0}

    def merge(i, j, rule, note=""):
        if uf.find(i) != uf.find(j):
            uf.union(i, j)
            merge_log.append({"rule": rule, "views": [i, j], "note": note})
            stats["merges"][rule] = stats["merges"].get(rule, 0) + 1

    # G1 同序号视图必同组（同号 = 同器物）。仅"外部绑定"（正下/上/侧，
    # rank<3）作同号证据：视图内部（rank3）标号多为拓片/器内纹饰的 OCR
    # 幻觉，不得借 G1 把异器物连锁并组。
    by_no = {}
    for v in views:
        for no, rank in zip(v["label_nos"], v.get("label_ranks", [])):
            if rank < 3:
                by_no.setdefault(no, []).append(v["id"])
    for no, ids in by_no.items():
        for k in range(1, len(ids)):
            merge(ids[0], ids[k], "G1_same_label", f"no={no}")

    # G2 连接符：短竖/横线两端视图相连（端点解析与 E2.1 共用
    # _resolve_link_ends——同侧多匹配取最近墨迹）
    _g2_binary = at.get("binary")
    for lk in at["links"]:
        b = lk["bbox"]
        end_a, end_b = _resolve_link_ends(views, b, _g2_binary, cfg)
        if end_a and end_b:
            merge(end_a[0], end_b[0],
                  "G2_connector_v" if (b[3] - b[1]) >= (b[2] - b[0])
                  else "G2_connector_h", str(b))
            continue
        # S4 轴线延伸：单端已解析、另一端为空时，沿连接符主轴向空端延伸
        if (end_a or end_b) and _g2_binary is not None:
            stats["s4_ext_attempt"] += 1
            empty = "a" if not end_a else "b"
            taken = ([end_a[0]] if end_a else []) \
                + ([end_b[0]] if end_b else [])
            hit = _extend_link_end(
                views, b, _g2_binary, taken, empty,
                text=(lk.get("text") or "").strip(), cfg=cfg)
            if hit is not None:
                vid, d_ext = hit
                fixed = (end_a or [vid])[0]
                partner = (end_b or [vid])[0]
                stats["s4_ext_merged"] += 1
                merge(fixed, partner,
                      "G2_connector_v_ext" if (b[3] - b[1]) >= (b[2] - b[0])
                      else "G2_connector_h_ext",
                      f"轴线延伸 墨距={d_ext} {b}")

    # S1 规则B连通分量闸：全图无外部绑定序号（rank<3）且视图数 >1 时，
    # 若 G1/G2 硬证据连接图的连通分量 >=2，说明图面呈现多个独立器物
    # 单元——按规范"无序号多物体图必须触发报警待人工复核，严禁强制
    # 配对"：跳过 G3/G4 几何吸附与 G0 全并，仅保留硬证据组合并输出报警。
    # 分量须在 G3 之前按 G1/G2 边计（G3 桥接后会漏报）。
    if n > 1 and not any(rk < 3 for v in views
                         for rk in v.get("label_ranks", [])):
        ncomp = len({uf.find(i) for i in range(n)})
        stats["s1_gate_components"] = ncomp
        if ncomp >= 2:
            stats["s1_gate_fired"] = 1
            merge_log.append({
                "rule": "G0_multi_object_alarm", "views": [],
                "note": f"无序号多物体图: G1/G2 硬证据连通分量={ncomp}>=2，"
                        f"按规范不合并、待人工复核"})
            at["e3_stats"] = stats
            groups = {}
            for i in range(n):
                groups.setdefault(uf.find(i), []).append(i)
            return [groups[k] for k in sorted(groups)], merge_log

    # S2 完整视图守卫：G3/G4 的 row/stack 几何自动并，若合并侧视图为
    # "完整视图"（bbox 面积 >= 0.5*全图视图面积中位数）且其就近
    # （<=label_gap）存在被 E2 丢弃/落选的序号信号，降级为 VL 确认；
    # VL 关闭 -> hold 不并并记待复核。双条件缺一不可。
    _dropped_status = ("conflict_dropped", "uniqueness_dropped",
                       "no_candidate", "invalid")

    def _label_status(lb):
        st = lb.get("_e2_status")                  # from-e2 复现路径
        if st and st != "unknown":
            return st
        if lb.get("_dropped_by_uniqueness"):       # live 路径按标记推断
            return "uniqueness_dropped"
        if lb.get("_conflict_dropped"):
            return "conflict_dropped"
        if lb.get("_attach") is not None:
            return "assigned"
        return "no_candidate"

    _areas = sorted((v["bbox"][2] - v["bbox"][0])
                    * (v["bbox"][3] - v["bbox"][1]) for v in views)
    _median_area = _areas[len(_areas) // 2] if _areas else 0

    def complete_ish(vid):
        vb = views[vid]["bbox"]
        return (vb[2] - vb[0]) * (vb[3] - vb[1]) >= 0.5 * _median_area

    def suspect_serial_near(vid):
        vb = views[vid]["bbox"]
        for lb in at["labels"]:
            if _label_status(lb) not in _dropped_status:
                continue
            bb = lb["bbox"]
            if max(bb[2] - bb[0], bb[3] - bb[1]) < 8:
                continue                            # 碎屑噪声
            gx = max(0, max(vb[0], bb[0]) - min(vb[2], bb[2]))
            gy = max(0, max(vb[1], bb[1]) - min(vb[3], bb[3]))
            if max(gx, gy) <= cfg.label_gap_max:
                return True
        return False

    def guard_needed(vid):
        return complete_ish(vid) and suspect_serial_near(vid)

    # G3 无标号组迭代吸附：逐轮评估"无标号组 -> 任意组"的最近成员对，
    # 直至收敛。候选按组内成员视图逐个判定——禁止用组并集大框制造虚假
    # 相邻；bbox 浅相交（交叠 < 0.5*较小面积）且目标组带标号时须 VL 确认
    def group_of(i):
        return uf.find(i)

    def group_members(gi):
        return [i for i in range(n) if group_of(i) == gi]

    def group_unlabeled(gi):
        return [i for i in group_members(gi) if not views[i]["label_nos"]]

    def pair_rel(ub, mb):
        """两视图 bbox 关系：('touch'|'touch_shallow'|'stack'|'row', gap) 或 None。"""
        ix = min(ub[2], mb[2]) - max(ub[0], mb[0])
        iy = min(ub[3], mb[3]) - max(ub[1], mb[1])
        gx, gy = bbox_gap(ub, mb)
        if ix > 0 and iy > 0:
            aa = (ub[2] - ub[0]) * (ub[3] - ub[1])
            ab_ = (mb[2] - mb[0]) * (mb[3] - mb[1])
            if ix * iy >= 0.5 * max(1, min(aa, ab_)):
                return ("touch", 0)
            return ("touch_shallow", 0)       # 浅相交：尖端互伸，存疑
        if gy > 0 and gy <= cfg.stack_gap_max:
            xov = bbox_hov(ub, mb) / max(1, min(ub[2] - ub[0],
                                                mb[2] - mb[0]))
            if xov >= cfg.stack_xov:
                return ("stack", gy)
        elif gx > 0 and gx <= cfg.row_gap_max:
            yov = bbox_vov(ub, mb) / max(1, min(ub[3] - ub[1],
                                                mb[3] - mb[1]))
            if yov >= cfg.row_yov:
                return ("row", gx)
        return None

    def try_merge(uid, gi, rels):
        """uid 组并入 gi 组：组内候选关系按 gap 升序逐个尝试（rels 元组
        为 (rule, gap, gi侧成员, uid侧成员)）；touch_shallow 且目标带标号
        时须 VL 把关，VL 拒后回退组内下一关系；目标无标号的
        touch_shallow 直接并。"""
        tgt_has_label = any(views[i]["label_nos"] for i in group_members(gi))
        for rule, gap, m, ui in sorted(rels, key=lambda r: r[1]):
            if rule == "touch_shallow":
                if not tgt_has_label:
                    stats["g3_touch_shallow_merge"] += 1
                    merge(uid, m, "G3_touch_shallow", f"gap={gap}")
                    return True
                stats["g3_touch_shallow_vl"] += 1
                stats["vl_touchpoints"] += 1
                same, vl_note = _same_artifact(
                    vl, at["bgr"], views[ui]["bbox"], views[m]["bbox"])
                if not same:
                    continue              # VL 拒：尝试组内下一关系
                stats["g3_touch_shallow_vl_merged"] += 1
                merge(uid, m, "G3_touch_shallow_vl", vl_note)
                return True
            # 远间隙行并降级：auto_max < gap <= row_gap_max 区间不再纯
            # 几何自动并，降级 VL 确认（VL 关 -> hold 保持独立）
            if rule == "row" and gap > cfg.row_auto_max:
                stats["g3_row_far_touchpoints"] += 1
                stats["vl_touchpoints"] += 1
                same, vl_note = _same_artifact(
                    vl, at["bgr"], views[ui]["bbox"], views[m]["bbox"])
                if not same:
                    stats["g3_row_far_holds"] += 1
                    merge_log.append({
                        "rule": "G3_row_far_hold", "views": [ui, m],
                        "note": f"远间隙行并 gap={gap}>"
                                f"{cfg.row_auto_max} 未获VL确认"
                                f"({vl_note or 'vl disabled'})，保持独立"})
                    continue              # 未获确认：尝试组内下一关系
                stats["g3_row_far_vl_merged"] += 1
                merge(uid, m, "G3_row_vl", vl_note)
                return True
            # S2 完整视图守卫：发起方为完整视图且就近有被丢弃序号信号时，
            # row/stack 几何自动并降级为 VL 确认（VL 关->hold 待复核）
            if rule in ("row", "stack") and guard_needed(ui):
                stats["s2_guard_touchpoints"] += 1
                stats["vl_touchpoints"] += 1
                same, vl_note = _same_artifact(
                    vl, at["bgr"], views[ui]["bbox"], views[m]["bbox"])
                if not same:
                    stats["s2_guard_holds"] += 1
                    merge_log.append({
                        "rule": "G3_guard_hold", "views": [ui],
                        "note": f"完整视图{rule}守卫未过({vl_note or 'vl disabled'})"
                                f"，不并入组{gi}待复核"})
                    continue              # 守卫未过：尝试组内下一关系
                stats["s2_guard_vl_merged"] += 1
                merge(uid, m, f"G3_{rule}_vl", vl_note)
                return True
            merge(uid, m, f"G3_{rule}", f"gap={gap}")
            return True
        return False

    changed = True
    while changed:
        changed = False
        done_roots = set()
        for uid in sorted((v["id"] for v in views if not v["label_nos"]),
                          key=lambda i: (views[i]["bbox"][1],
                                         views[i]["bbox"][0])):
            if any(no for no in views[uid]["label_nos"]):
                continue
            root = group_of(uid)
            if root in done_roots or len(group_unlabeled(root)) == 0:
                continue
            if root in {group_of(i) for i in range(n)
                        if views[i]["label_nos"]}:
                continue                          # 组内已带号：不作 G3 发起方
            done_roots.add(root)
            # 组级候选关系：uid 自身关系全类型参与；组内其他成员仅代理
            # "相交类强证据"（touch/touch_shallow——接触面属于整个组）。
            # stack/row 弱邻近不代理：细长视图嵌套会造出 xov=1 的伪 stack。
            ub_members = group_members(root)
            cands = {}                    # group_root -> [(rule,gap,mi,ui)]
            for gi in {group_of(i) for i in range(n)}:
                if gi == root:
                    continue
                for mi in group_members(gi):
                    mb = views[mi]["bbox"]
                    best = None
                    for ui in ub_members:
                        rel = pair_rel(views[ui]["bbox"], mb)
                        if rel is None:
                            continue
                        if ui != uid and rel[0] not in ("touch",
                                                        "touch_shallow"):
                            continue      # 组员代理仅限相交类
                        if best is None or rel[1] < best[1]:
                            best = (rel[0], rel[1], mi, ui)
                    if best is not None:
                        cands.setdefault(gi, []).append(best)
            if not cands:
                continue                  # 孤立：保持独立（报警在汇总判定）
            ordered = sorted(
                cands.items(),
                key=lambda kv: min(r[1] for r in kv[1]))
            if len(ordered) == 1 or \
                    min(r[1] for r in ordered[1][1]) >= \
                    2 * min(r[1] for r in ordered[0][1]) + 8:
                gi, rels = ordered[0]
                if try_merge(uid, gi, rels):
                    changed = True
            else:
                # 多候选歧义：VL 兜底裁决（分别与最近两组的成员视图成对
                # 判断；VL 均否/不可用 -> 放弃合并，保持独立并记录待复核）
                stats["g3_ambiguous"] += 1
                stats["vl_touchpoints"] += 2
                (g1, rels1), (g2, rels2) = ordered[0], ordered[1]
                m1, u1 = min(rels1, key=lambda r: r[1])[2:4]
                m2, u2 = min(rels2, key=lambda r: r[1])[2:4]
                same1, note1 = _same_artifact(
                    vl, at["bgr"], views[u1]["bbox"], views[m1]["bbox"])
                same2, note2 = None, ""
                if same1 is not True:
                    same2, note2 = _same_artifact(
                        vl, at["bgr"], views[u2]["bbox"], views[m2]["bbox"])
                if same1:
                    stats["g3_vl_merged"] += 1
                    merge(uid, m1, "G3_vl", note1)
                    changed = True
                elif same2:
                    stats["g3_vl_merged"] += 1
                    merge(uid, m2, "G3_vl", note2)
                    changed = True
                else:
                    stats["g3_abandon"] += 1
                    if same1 is None or (same1 is not True and same2 is None):
                        stats["g3_vl_unresolved"] = \
                            stats.get("g3_vl_unresolved", 0) + 1
                    merge_log.append({"rule": "G3_vl_abandon", "views": [uid],
                                      "note": f"多候选歧义放弃: {note1} | {note2}"})

    # G4 带号单例视图吸附无标号组：序号只标在器物某一个视图上时，其余
    # 视图已自成无号组——带号视图须把紧邻的无号组吸回来，组号随之覆盖
    # 全组。阈值比 G3 严：gap<=30、重分布>=0.5，多候选 VL。
    changed = True
    while changed:
        changed = False
        for v in views:
            if not v["label_nos"]:
                continue
            root = group_of(v["id"])
            if len(group_members(root)) != 1:
                continue                          # 只吸附"带号单例"所在组
            ub = v["bbox"]
            cands = {}
            for gi in {group_of(i) for i in range(n)}:
                if gi == root or group_unlabeled(gi) != group_members(gi):
                    continue                      # 目标必须整组无标号
                for mi in group_members(gi):
                    mb = views[mi]["bbox"]
                    rel = pair_rel(ub, mb)
                    if rel is None:
                        continue
                    rule, gap = rel
                    if rule == "touch_shallow":
                        ix2 = min(ub[2], mb[2]) - max(ub[0], mb[0])
                        iy2 = min(ub[3], mb[3]) - max(ub[1], mb[1])
                        aa2 = (ub[2] - ub[0]) * (ub[3] - ub[1])
                        ab2 = (mb[2] - mb[0]) * (mb[3] - mb[1])
                        if ix2 * iy2 < 0.15 * max(1, min(aa2, ab2)):
                            continue              # G4 更保守：极浅相交不吸
                    if (rule == "stack" and gap > 30) \
                            or (rule == "row" and gap > 30):
                        continue
                    if gi not in cands or gap < cands[gi][1]:
                        cands[gi] = (rule, gap, mi)
            if not cands:
                continue
            ordered = sorted(cands.items(), key=lambda kv: kv[1][1])
            if len(ordered) == 1 or ordered[1][1][1] >= 2 * ordered[0][1][1] + 8:
                gi, (rule, gap, mi) = ordered[0]
                # S2 完整视图守卫（G4 侧）：被吸组内存在"完整视图且就近
                # 有被丢弃序号信号"的成员时，吸附降级为 VL 确认
                susp = next((x for x in group_members(gi)
                             if guard_needed(x)), None)
                if susp is not None:
                    stats["s2_guard_touchpoints"] += 1
                    stats["vl_touchpoints"] += 1
                    same, vl_note = _same_artifact(
                        vl, at["bgr"], views[v["id"]]["bbox"],
                        views[susp]["bbox"])
                    if not same:
                        stats["s2_guard_holds"] += 1
                        merge_log.append({
                            "rule": "G4_guard_hold", "views": [v["id"]],
                            "note": f"被吸组{gi}完整视图V{susp}守卫未过"
                                    f"({vl_note or 'vl disabled'})，不吸附待复核"})
                        continue
                    stats["s2_guard_vl_merged"] += 1
                    stats["g4_absorb"] += 1
                    merge(v["id"], susp, f"G4_{rule}_vl", vl_note)
                    changed = True
                    continue
                stats["g4_absorb"] += 1
                merge(v["id"], mi, f"G4_{rule}", f"gap={gap}")
                changed = True
            else:
                stats["g4_ambiguous"] += 1
                stats["vl_touchpoints"] += 2
                (g1, (r1, d1, m1)), (g2, (r2, d2, m2)) = ordered[0], ordered[1]
                same1, note1 = _same_artifact(vl, at["bgr"], ub,
                                              views[m1]["bbox"])
                same2, note2 = None, ""
                if same1 is not True:
                    same2, note2 = _same_artifact(vl, at["bgr"], ub,
                                                  views[m2]["bbox"])
                if same1:
                    stats["g4_vl_merged"] += 1
                    merge(v["id"], m1, "G4_vl", note1)
                    changed = True
                elif same2:
                    stats["g4_vl_merged"] += 1
                    merge(v["id"], m2, "G4_vl", note2)
                    changed = True
                else:
                    stats["g4_abandon"] += 1
                    if same1 is None or (same1 is not True and same2 is None):
                        stats["g4_vl_unresolved"] = \
                            stats.get("g4_vl_unresolved", 0) + 1
                    merge_log.append({"rule": "G4_vl_abandon",
                                      "views": [v["id"]],
                                      "note": f"带号吸附歧义放弃: {note1} | {note2}"})

    # 全图无正文序号 -> 规则B：全部视图归一组
    if not any(v["label_nos"] for v in views) and n > 1:
        for k in range(1, n):
            merge(0, k, "G0_no_serial_ruleB", "全图无序号，按单物体多视图合并")

    groups = {}
    for i in range(n):
        groups.setdefault(group_of(i), []).append(i)
    at["e3_stats"] = stats
    return [groups[k] for k in sorted(groups)], merge_log


# ---------------------------------------------------------------------------
# E4 比例尺绑定（L1 前缀硬匹配 > L2 唯一尺共享 > L3 VL 兜底 > 放弃）
# ---------------------------------------------------------------------------
def bind_scales(at, groups, vl=None, cfg=None):
    """返回 (group_scales: [ [ {si, source, prefix_nos, shared} ] ],
    scale_records, alarms)。绑定严禁坐标距离：只用前缀序号文本。"""
    cfg = cfg or AssemblyConfig()
    scales = at["scales"]
    prefix_nos_of = []

    def expand_prefix_nums(text):
        """前缀序号集合：支持连续列举（'1、2.'）与范围（'1~7.'，跨度
        <=30 防误扩）。"""
        nums = set()
        t = text or ""
        for m in re.finditer(r"(\d{1,2})\s*([~～\-—–])\s*(\d{1,2})", t):
            a, b = int(m.group(1)), int(m.group(3))
            if 0 < a <= b <= a + 30:
                nums.update(range(a, b + 1))
        nums.update(int(x) for x in re.findall(r"\d{1,2}", t))
        return nums

    def scale_prefix_nums(si):
        """比例尺前缀序号集合：尺行前缀序号（含跨 token 范围展开）+
        raw_text 前缀段。绑定严禁坐标距离，只用序号文本证据。"""
        bb = scales[si].get("bar_bbox") or scales[si]["bbox"]
        band_top = bb[1] - 12
        band_dn = bb[3] + 12
        ext = cfg.prefix_ext
        # 多尺同行划界：收集左界不得越过左邻比例尺的右缘（防前缀跨尺互吸）
        left_bound = bb[0] - ext
        other_bars = [(s.get("bar_bbox") or s["bbox"])
                      for j, s in enumerate(scales) if j != si]
        for ob_b in other_bars:
            if ob_b[2] <= bb[0]:                      # 左邻尺：整体在本尺左侧
                left_bound = max(left_bound, ob_b[2] + 8)
        row = [s for s in at["prefixes"]
               if s["bbox"][3] >= band_top and s["bbox"][1] <= band_dn
               and left_bound <= s["bbox"][2] <= bb[0] + 6]
        row.sort(key=lambda s: s["bbox"][0])
        toks = [(s["bbox"],
                 [int(x) for x in re.findall(r"\d{1,2}", s["text"])])
                for s in row]
        nums = set()
        ranged = set()
        binary = at["binary"]
        for k in range(len(toks) - 1):
            (b1, n1), (b2, n2) = toks[k], toks[k + 1]
            gap = b2[0] - b1[2]
            if not (0 <= gap <= 45) or not n1 or not n2:
                continue
            a_val, b_val = n1[-1], n2[0]
            if not (0 < a_val <= b_val <= a_val + 30):
                continue
            # 间隙墨迹形态判定（R6 修复）：仅"居中横条"（～/—/–）视为
            # 范围符并展开 a~b；底部小点（、）只证明列举关系，严禁展开
            y0 = max(b1[1], b2[1]) - 2
            y1 = min(b1[3], b2[3]) + 2
            sub = binary[max(0, y0):y1, max(0, b1[2]):b2[0]]
            if sub.any():
                n_lab, lab, stats, _cent = cv2.connectedComponentsWithStats(
                    sub.astype(np.uint8), connectivity=8)
                if n_lab > 1:
                    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                    bx, by, bw, bh = (stats[best, cv2.CC_STAT_LEFT],
                                      stats[best, cv2.CC_STAT_TOP],
                                      stats[best, cv2.CC_STAT_WIDTH],
                                      stats[best, cv2.CC_STAT_HEIGHT])
                    h_tok = max(1, min(b1[3], b2[3]) - max(b1[1], b2[1]))
                    cy_rel = (by + bh / 2.0) / h_tok
                    if bw >= 4 and bh <= max(6, 0.7 * h_tok) \
                            and cy_rel <= 0.85:       # 居中横条 -> 范围符
                        nums.update(range(a_val, b_val + 1))
                        ranged.update({k, k + 1})
        for k, (_b, ns) in enumerate(toks):
            if k not in ranged:
                nums.update(ns)
        # 前缀兜底（R6 收紧）：整段前缀被 OCR 低置信丢弃进 others 时，
        # 吸收与本尺已收 token 水平相邻（间隙<=20px）的可信单元；
        # scale_zone 是已证认的尺上杂物不采信；lowconf 紧贴 token（间隙
        # <8px）的小点是列举符 '、' 的幻觉读值，按间隙区分
        for o in at["others"]:
            ob = o.get("bbox")
            txt = (o.get("text") or "").strip()
            if not ob or not txt or not re.search(r"\d", txt):
                continue
            if o.get("reason") in ("scale_zone", "fig_zone", "connector",
                                   "sliver", "tiny"):
                continue
            if ob[3] >= band_top and ob[1] <= band_dn \
                    and left_bound <= ob[2] <= bb[0] + 6:
                near = min((min(abs(ob[0] - tb[2]), abs(tb[0] - ob[2]))
                            for tb, _tn in toks), default=99)
                if toks and near > 20:
                    continue
                # lowconf 紧贴已收 token（间隙<8px）的小点是列举符 '、'
                # 的幻觉读值；本尺 row 为空时无附着对象，lowconf 整段
                # 前缀恰是兜底要救的目标，放行
                if o.get("reason") == "lowconf" and toks and near < 8:
                    continue
                # 范围碎片展开：'2~5.' 被拆成 token '2' + 碎片 '~5.' 时，
                # 按"左邻 token 号 ~ 碎片右端号"补全展开
                m_rng = re.match(r"^[~～—–\-]\s*(\d{1,2})", txt)
                if m_rng and toks:
                    b_val = int(m_rng.group(1))
                    lefts = [(tb, ns) for tb, ns in toks
                             if 0 <= ob[0] - tb[2] <= 20]
                    if lefts:
                        tb, ns = max(lefts, key=lambda t: t[0][2])
                        a_val = max(ns) if ns else None
                        if a_val and 0 < a_val <= b_val <= a_val + 30:
                            nums.update(range(a_val, b_val + 1))
                            nums |= expand_prefix_nums(txt)
                            continue
                nums |= expand_prefix_nums(txt)
        pv = _parse_scale_text(scales[si].get("raw_text") or "")
        # band OCR 粘连读出的前缀段（如 '1.02厘米' 的 '1'）可信度低：
        # 仅当其数字与本尺已收 token 有交集（或本尺完全没有 token）时采信
        pv_nums = expand_prefix_nums(pv.get("prefix") or "")
        row_nums = {x for _b, ns in toks for x in ns}
        if not toks or (pv_nums & row_nums):
            nums |= pv_nums
        return nums

    for si in range(len(scales)):
        prefix_nos_of.append(scale_prefix_nums(si))

    # L1.5 前缀漏检 VL 补救：规则收集后仍无前缀的尺（整段前缀被 OCR
    # 漏读/粘连损毁），送 VL 读尺行前缀补齐。仅多尺图触发：单尺图本就
    # 无前缀标注（L2 唯一共享天然覆盖），对其调 VL 是纯浪费。
    vl_assisted = {}
    if vl is not None and len(scales) > 1:
        for si in range(len(scales)):
            if prefix_nos_of[si]:
                continue
            nums, note = vl.read_scale_prefix(
                bgr=at["bgr"], scale=scales[si], where="scale_prefix")
            if nums:
                prefix_nos_of[si] = set(nums)
                vl_assisted[si] = note

    group_nos = []
    for g in groups:
        nos = set()
        for i in g:
            for no in at["views"][i]["label_nos"]:
                if no.isdigit():
                    nos.add(int(no))
        group_nos.append(nos)

    bound = [[] for _ in groups]                  # 每组绑定的 (si, source, shared)
    scale_used = [False] * len(scales)

    # L1 前缀硬匹配
    for si in range(len(scales)):
        for gi, nos in enumerate(group_nos):
            if nos and (prefix_nos_of[si] & nos):
                bound[gi].append({"si": si, "source": "L1_prefix",
                                  "prefix_nos": sorted(prefix_nos_of[si]),
                                  "shared": len(prefix_nos_of[si]) > 1})
                scale_used[si] = True

    # L2 全图唯一比例尺 -> 全局默认共享
    if len(scales) == 1 and not scale_used[0]:
        for gi in range(len(groups)):
            bound[gi].append({"si": 0, "source": "L2_unique_shared",
                              "prefix_nos": sorted(prefix_nos_of[0]),
                              "shared": True})
        scale_used[0] = True

    # L3 VL 兜底：仍未绑定的尺（多尺场景）
    alarms = []
    scale_records = []
    for si in range(len(scales)):
        rec = {"scale_id": si, "bbox": scales[si]["bbox"],
               "text": scales[si].get("text", ""),
               "value": scales[si].get("value"),
               "unit": scales[si].get("unit"),
               "prefix_nos": sorted(prefix_nos_of[si]),
               "verified": scales[si].get("verified", True)}
        if si in vl_assisted:
            rec["vl_assisted"] = vl_assisted[si]
        if not scale_used[si]:
            if vl is None:
                nums, note = None, "vl disabled"
            else:
                nums, note = vl.read_scale_prefix(bgr=at["bgr"],
                                                  scale=scales[si],
                                                  where="L3")
            hit = False
            if nums:
                for gi, nos in enumerate(group_nos):
                    if set(nums) & nos:
                        bound[gi].append({"si": si, "source": "L3_vl",
                                          "prefix_nos": sorted(set(nums)),
                                          "shared": len(set(nums)) > 1})
                        scale_used[si] = True
                        hit = True
                        rec["vl_note"] = note
                        break
            if not hit:
                rec["abandoned"] = True
                rec["vl_note"] = note
                alarms.append({
                    "code": "scale_unbound",
                    "msg": f"⚠ 报警：比例尺{si}（{rec['text']!r}）无前缀且"
                           f"无法硬绑（L1/L2/L3 均失败），放弃绑定待复核",
                    "scale_id": si, "note": note,
                    "vl_unresolved": nums is None})   # None=VL 不可用（E007 候选）
            scale_records.append(rec)
            continue
        scale_records.append(rec)

    # 组无任何比例尺 -> 报警（VL 已在 L3 尝试过全部未绑尺）
    for gi in range(len(groups)):
        if not bound[gi]:
            alarms.append({"code": "group_no_scale",
                           "msg": f"⚠ 报警：器物组{gi} 未绑定任何比例尺",
                           "group": gi})
    return bound, scale_records, alarms

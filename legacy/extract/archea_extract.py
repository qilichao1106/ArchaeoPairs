#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ============================================================================
# archea_extract.py - 独立器物提取：分组 + 比例尺绑定 + 组装（CV 规则 + VL 兜底）。
#
# 定位（archea_seg / archea_rec 的下游合成模块）：
#   在分割（archea_seg.extract_contours）与识别（archea_rec：比例尺/器物序号）
#   的基础上，把一张图版中的各个器物分割为独立输出：
#     E1 build_atoms    原子收集：视图(轮廓+填充掩膜)/正文序号/比例尺组/连接符；
#                       R1 小尺寸视图救援（others 中被 OCR 误读的圆形/封闭视图
#                       回捞为独立视图）；
#                       R2 嵌套碎片吸收（bbox 包含 + 掩膜级 >=60% 真实包含，
#                       细长条豁免；吸收事件报警 fragment_absorbed）
#     E2 bind_labels    序号→视图归属：全部候选收集 + 全局贪心分配（视图被异号
#                       占据时序号自动迁移次优候选）；内部候选仅在视图无外部
#                       标号时生效；左右侧候选 gap 上限收紧防相邻小视图抢号；
#                       R3b 刚性竞争置信度驱逐（低置信在位者被高置信挑战者
#                       取代，被驱逐者留痕报警）；R3c 空白角墨迹纠正（bbox
#                       空白角内的序号按二值墨迹换算为下/上外部关系，同号
#                       更高置信重复者守卫跳过）；E2.1 连接符继承（断裂符
#                       "一端有号、一端无号"时无号视图继承该号，rank4 不作
#                       G1 证据，分组仍由 E3 G2 完成；同侧多匹配取最近墨迹，
#                       _resolve_link_ends 与 E3 G2 共用）
#     R5 断裂符恢复     E1 连接符收集的"视图内部装饰短线"过滤升级为墨迹级
#                       （bbox 包含且局部墨迹密度 >= 0.10 才判装饰线）——
#                       大视图 bbox 吞入的空白区断裂符（002 V5↔V6/V8↔V9）
#                       不再误删；from-e1 复现模式按现行规则从存储 others
#                       重建连接符（load_atoms_from_e1），全库恢复 33 条
#     K1/K2 排版先验    业务规则落地（考古线图）：K1 同号唯一（一张线图上
#                       同一器物序号只印一次，例外位"比例尺左侧"由 E1 归入
#                       prefixes）→ R7 同号多绑按 (rank,conf) 择优留一；
#                       K2 序号只在视图下侧 → E2 上方关系不生成候选（无候选
#                       留痕报警）、R3c 只换算 below、E2.5 rescue 不采上方；
#                       正下方判定改序号中心 cy 过下缘（兼容骑跨印刷位），
#                       gap<0 时要求 x 向实际交叠（防邻框外缘抢号）
#     E3 group_views    并查集分组：G1同序号 > G2连接符 > G3无标号组迭代吸附
#                       （目标带标号须 VL 把关、浅相交守卫）> G4带号单例吸附
#                       紧邻无标号组（组号传播）> VL兜底
#     E4 bind_scales    docx 分级：L1前缀序号硬匹配 > L2唯一尺全局共享 >
#                       L3 VL读前缀兜底 > 放弃并报警；
#                       R6 前缀解析加固：范围符连通域形态判定（～/—居中横条
#                       才展开，顿号仅列举）、多尺同行划界、lowconf/scale_zone
#                       幻觉单元不采信、band 粘连前缀段须与 token 交叠
#     E5 compose_group  每组组装输出：白底画布 + 原图像素掩膜粘贴；
#                       视图/连接符/说明文字严格保持原图相对关系（仅整体平移），
#                       不缩放、不旋转、不重排；比例尺整组置于画布底部。
#                       成品默认剔除器物序号数字与比例尺左侧前缀数字
#                       （strip_serial_digits / strip_scale_prefix，
#                       CLI --keep-serial-digits / --keep-scale-prefix 恢复）。
#
# 规范对应（解析说明.docx）：
#   - 掩膜提取、禁矩形切割：视图用轮廓填充掩膜，文字/序号/尺成员用墨迹掩膜，
#     粘贴原图像素（保留印刷噪点），绝不做 bbox 矩形裁剪成图。
#   - 掩膜范围 = 线图 + 说明文字 + 专属比例尺（序号/前缀参与分组与绑定，
#     按需求默认不画入成品图，bbox 记录保留于 JSON）。
#   - 比例尺归属三级规则：严禁坐标距离匹配，只用序号文本硬性对应；
#     唯一比例尺 = 全局默认共享（复制给每器物）；多尺无前缀无法匹配 → 报警。
#   - 命名回退（无器物号 XML）：原图名称_图片内序号.png；无序号组用 01/02 递增。
#   - 报警策略（用户决策）：先 VL（Qwen3-VL，archea_vl.QwenVL）二次判断兜底，
#     每次兜底记录 source（cv_rule / vl / abandoned）与 VL 依据；VL 仍失败 →
#     放弃绑定并记录 wait_review（默认仍出图便于检查，--strict-docx 则整图停发）。
#
# 输出（--out 根目录，默认 out_extract/）：
#   <stem>/<stem>_<seq>.png    每器物一张（白底、掩膜粘贴、比例尺置底）
#   <stem>/<stem>_overlay.png  分组/绑定叠加可视化
#   <stem>/<stem>_groups.json  结构化记录（成员/绑定来源/报警/VL记录）
#   <stem>/<stem>_e1.json      E1-only 原子收集产物（--e1-only，供展示端）
#   <stem>/<stem>_e2.json      E2-only 序号绑定产物（--e2-only / --from-e1，
#                              含逐序号候选清单/归属/未绑定原因 + 评估指标）
#   <stem>/<stem>_e3.json      E3-only 视图分组产物（--e3-only / --from-e2，
#                              含逐组成员/组号/合并证据链/孤立无号组 + 评估指标）
#   batch_summary.json         批量汇总（--all / 多图时）
#
# 用法：
#   python3 archea_extract.py test_imgs/image101.jpg            # 单图/多图
#   python3 archea_extract.py --sample                          # 5 张抽样
#   python3 archea_extract.py --all                             # test_imgs 全量
#   python3 archea_extract.py image101.jpg --no-vl --strict-docx --out out_x
#   python3 archea_extract.py --all --e1-only --out out_e1
#                              # 分阶段评估：仅运行 E1 原子收集 build_atoms
#                              # （E2~E5 注释停用），产物 <stem>_e1.json
#                              # 供独立可视化脚本 archea_show_e1.py 展示
#   python3 archea_extract.py --all --e2-only --out out_e2
#                              # 分阶段评估：E1 原子收集（含 E1.5 VL 复核）后
#                              # 只运行 E2 bind_labels（E3~E5 停用），产物
#                              # <stem>_e2.json 供 archea_show_e2.py 展示
#   python3 archea_extract.py --all --from-e1 --out out_e2
#                              # E2 单独评估迭代（推荐）：不重跑 E1，直接读取
#                              # <root>/<stem>/<stem>_e1.json（--from-e1 根目录，
#                              # 默认 out_e1）中的 E1 原子执行 E2——免 OCR/VL 调用，
#                              # 与 out_e1 基线完全一致，秒级复现，便于反复调参
#                              # （可视化：python3 archea_show_e2.py --root out_e2）
#   python3 archea_extract.py --all --e3-only --out out_e3
#                              # 分阶段评估：E1 原子收集（含 E1.5 VL 复核）+
#                              # E2 bind_labels（含 E2.1 连接符继承）后只运行
#                              # E3 group_views（E4~E5 停用），产物
#                              # <stem>_e3.json 供 archea_show_e3.py 展示
#   python3 archea_extract.py --all --from-e2 --out out_e3 [--no-vl]
#                              # E3 单独评估迭代（推荐）：不重跑 E1/E2，直接读取
#                              # <root>/<stem>/<stem>_e2.json（--from-e2 根目录，
#                              # 默认 out_e2）中的 E2 绑定结果执行 E3——免 OCR/免
#                              # 分割/免 E1.5，与 out_e2 基线完全一致，秒级复现。
#                              # 默认开启 VL（E3 的 G3/G4 歧义仲裁真实需要）；
#                              # --no-vl 时纯 CV 规则快速迭代（VL 触点仍在
#                              # metrics.vl_touchpoints 留痕，便于估算 VL 依赖）
#                              # （可视化：python3 archea_show_e3.py --root out_e3）
#
# 依赖：cv2 / numpy / pillow；VL 兜底另需 archea_vl.QwenVL（DASHSCOPE_API_KEY，
#       缺失或调用失败自动放弃并记录，不阻塞主流程）；OCR 需 paddleocr。
# ============================================================================ #
"""独立器物提取：分组+比例尺绑定+组装（CV 规则链 + VL 兜底，证据与来源全记录）。"""

import argparse
import glob as _glob
import json
import os
import re
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from archea_seg import extract_contours, load_image
from archea_rec import (ArcheaRec, _box_intersects, _clean_prefix,
                        _parse_scale_text, imread_cn)

SAMPLE_IMAGES = ["image101.jpg", "image115.jpg", "image246.jpg",
                 "image250.jpg", "image400.jpg"]
DASH_LIKE = {"一", "—", "–", "-", "―", "~", "～", "—"}
# R1 视图救援：小尺寸圆形/封闭视图被 OCR 误读的常见字符
O_FACTOR = {"O", "o", "0", "口", "D", "Q", "〇", "○", "Ο", "ο", "Θ",
            "O.", "o.", "0.", "O:", "0:", "C", "c", "U", "u", "Â",
            "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
            "⊙", "¤", "ø", "Ø", "e", "6", "9", "b", "p", "d", "q"}


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

    用途：区分"空白区断裂符"与"成片墨迹场内的斑点/装饰短线"。
    断裂符印在空白处——紧邻 12px 半径内除自身外基本无墨（全库实测
    21 个被误滤断裂符 pad12 密度 0.001~0.108）；拓片币面麻点场内的
    斑点（image76 '-'@898,684，pad12=0.128）与剖切符号短竖（image73
    '|'@287,217，pad12=0.108——竖线+剖面阴影块为剖切标记）则明显更
    高。阈值 0.10。注意不可用更大半径：002 的断裂符位于两视图之间
    4px 窄缝，pad>=20 时窗口被邻接视图墨迹淹没（0.194）失去区分度。
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


# ---------------------------------------------------------------------------
# VL 兜底仲裁：实现已统一抽取封装至 archea_vl.VlArbiter（三态返回 + records
# 留痕 + 调用统计 + 六个场景包装），此处仅导入使用。
# ---------------------------------------------------------------------------
from archea_vl import VlArbiter, unit_ink_mask


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------
class ArcheaExtract:
    """独立器物提取（分组 + 比例尺绑定 + 组装）。"""

    def __init__(self, out_root="out_extract", vl=True, strict_docx=False,
                 margin_pct=0.03, label_gap_max=60, link_gap=52,
                 stack_gap_max=90, row_gap_max=110, row_auto_max=97,
                 stack_xov=0.45,
                 row_yov=0.45, attach_text_gap=18, rec=None,
                 strip_serial_digits=True, strip_scale_prefix=True,
                 e1_only=False, e2_only=False, e3_only=False, e3_rescue=True,
                 review_sheet=False,
                 evict_conf_floor=0.7, evict_conf_margin=0.3,
                 ink_corner_fix=True, stiff_evict=True):
        self.out_root = out_root
        self.strict_docx = strict_docx
        self.margin_pct = margin_pct
        self.p_label_gap = label_gap_max
        self.p_link_gap = link_gap
        self.p_stack_gap = stack_gap_max
        self.p_row_gap = row_gap_max
        # 远间隙行并自动并上限：合法 row 合并实测最大 gap=97（389），上限
        # 区间 (auto_max, row_gap_max] 降级 VL 确认（134 的 109 误并即在此区间）
        self.p_row_auto_max = row_auto_max
        self.p_stack_xov = stack_xov
        self.p_row_yov = row_yov
        self.p_attach_gap = attach_text_gap
        # 输出净化：成品图不画序号数字 / 比例尺前缀数字（仍参与分组与绑定，
        # 且 JSON members/scales 记录保留）。置 False 恢复旧行为。
        self.strip_serial_digits = strip_serial_digits
        self.strip_scale_prefix = strip_scale_prefix
        # 分阶段评估开关：True 时 extract_image 只运行到 E1 原子收集
        # （build_atoms），E2~E5 注释停用，产物落盘 <stem>_e1.json
        self.e1_only = e1_only
        # 分阶段评估开关：True 时 extract_image 运行到 E2 序号绑定
        # （E1 原子收集 + E1.5 VL 复核 + bind_labels），E3~E5 停用，
        # 产物落盘 <stem>_e2.json（E2 单独效果评估，见 _e2_result）
        self.e2_only = e2_only
        # 分阶段评估开关：True 时 extract_image 运行到 E3 视图分组
        # （E1 原子收集 + E1.5 VL 复核 + bind_labels + group_views），
        # E4~E5 停用，产物落盘 <stem>_e3.json（E3 单独效果评估，
        # 见 _e3_result；批量复现迭代用 --from-e2 更快）
        self.e3_only = e3_only
        # e3-only 是否执行 E2.5 回捞：from-e2 重放路径的 out_e2 已烘焙回捞
        # 结果，新跑路径若跳过则两种 E3 输入口径不一致（合理化对齐：默认
        # 执行，与全流程一致；--e3-no-rescue 可退回旧口径）
        self.e3_rescue = e3_rescue
        # E1.5 复核标注图开关：把 VL 二次判定/报警结果画回原图输出
        # <stem>_vl_review.png（仅人工复核展示，不参与判定）
        self.review_sheet = review_sheet
        # E2 R3b 置信度驱逐：同视图异号竞争且挑战者为刚性（无次优候选）时，
        # 在位者 conf < evict_conf_floor 且挑战者 conf >= 在位者 +
        # evict_conf_margin 时，在位者让位（image431 断裂符误读 '1'@0.5
        # 曾抢走真序号 '2'@1.0 的视图）
        self.evict_conf_floor = evict_conf_floor
        self.evict_conf_margin = evict_conf_margin
        # E2 优化开关（A/B 评估用；False = 退回基线行为）
        self.ink_corner_fix = ink_corner_fix      # R3c 空白角墨迹纠正
        self.stiff_evict = stiff_evict            # R3b 刚性竞争置信度驱逐
        self.rec = rec or ArcheaRec()          # 共享 OCR 后端（初始化一次）
        self.vl = VlArbiter(enabled=vl)

    # ------------------------------------------------------------------
    # E1 原子收集
    # ------------------------------------------------------------------
    def build_atoms(self, bgr):
        """分割 + 识别 -> 原子 dict（视图带轮廓/填充掩膜；小元素用 bbox+墨迹）。"""
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        kept, _removed, _bin = extract_contours(
            gray, self.rec.p["dilate_k"], self.rec.p["min_area"])
        r = self.rec.recognize(bgr, kept)
        H, W = bgr.shape[:2]
        _, binary = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary = binary > 0

        # 轮廓索引：bbox tuple -> contour（figures/bars 的 bbox 与 kept 完全一致）
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
        # 'O'/'0'/'口' 或整体 unreadable 时，从 others 中回捞为独立视图
        # （image104/138/141 的圆形俯视图、image16/76 的局部小视图均属此类）。
        # 救援视图标记 rescued=True，供 JSON 追溯；不与现有视图/比例尺重叠。
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
        # E1 救援判定 VL 化（S2 补救场景三）：候选批量送 VL 筛查"是否器物
        # 视图"，滤掉 O 形符号/装饰圈/图内杂符等假候选；判定器统一走 v2
        # （掩膜白底裁片 ≤128 + PROMPT_V3 + 分块 ≤8，2026-09 实测定稿）。
        # 三态语义：True 采纳 / False 弃 / None（批调用或解析失败）维持
        # 规则结果——VL 不可用时按规则候选全部采纳，不阻塞主流程。
        if rescue_cands and self.vl.enabled:
            flags, _note = self.vl.judge_view_candidates_v2(
                bgr, [{"bbox": cnd[2]} for cnd in rescue_cands],
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
        # 紧邻其左侧的序号是尺带标注（图版常在比例尺左端标器物号），不是
        # 器物视图序号——归入 prefixes 供 E4 L1 前缀硬匹配使用，不再与
        # 器物序号竞争绑定
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
        # 连接符候选：connector 类 + 破折形文本（含 fig_zone 中的 '一'，耳环钩环
        # 间短横线常落此分类）+ 细长小组件（短竖线/短横线，含被读成 '1'/'I'/
        # '1-1'/'|—1' 的刻度式连接线）；"视图内部装饰短线"须墨迹级确认（R5）：
        # 大视图 bbox 常把邻近小视图及其间空隙一并吞入（002 的 V0 大框吞掉
        # V8/V9 间隙与 V5/V6 断裂符），落在 bbox 空白区的断裂符不得按 bbox
        # 包含误删——仅局部墨迹密度 >= 0.3（器物墨迹包围）才判装饰线
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
        # 剖面碎片（如簪身双线内壁残段），不是独立器物——并入外层视图。
        # R2 收紧：bbox 包含之外还须"掩膜级真实包含"（小视图填充区 >=60% 落在
        # 大视图填充区内）——bbox 大框包含不等于器内碎片（002 大钉 bbox 曾吞掉
        # 旁侧真 6 号的小钉/弯钩：钉形掩膜外的大片空白 bbox 也能"包含"邻居）。
        drop = set()
        fragments = {}
        absorbed_events = []   # E1 评估留痕：吸收事件（宿主旧id+碎片bbox/面积）
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
                        # 细长条（h/w>=8，笔画残段/中缝墨线）直接吸收——
                        # 其位于器物双线夹缝内，轮廓常未闭合而填不出该区域
                        pass
                    else:
                        # 掩膜级真实包含：碎片墨迹 >=60% 落在宿主掩膜膨胀 9px
                        # 的范围内（紧贴宿主笔画的器内细部才算碎片；002 大钉
                        # bbox 曾吞掉旁侧真 6 号的小钉/弯钩——它们离钉体笔画
                        # 远，膨胀后仍不接触）
                        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19))
                        bm_d = cv2.dilate(bm.astype(np.uint8), k) > 0
                        inter = int((am & bm_d).sum())
                        if inter < 0.6 * int(am.sum()):
                            continue                  # 掩膜不接触：并排视图，保留
                # E1 吸收判定 VL 化（S2 补救场景三）：仅对"真有歧义"的吸收
                # 对确认——掩膜验证通过且碎片面积占宿主 >5%（较大碎片是否
                # 独立器物存在不确定性）。细长条豁免路径与微小碎片（<5%）
                # 规则置信充分，直接按规则吸收（001 中缝残段曾被 VL 误判
                # 为独立器物而拆出假组）；VL 拒绝则保留为独立视图。
                if self.vl.enabled:
                    aa_host = (bb[2] - bb[0]) * (bb[3] - bb[1])
                    aa_frag = (ab[2] - ab[0]) * (ab[3] - ab[1])
                    if aa_frag > 0.05 * aa_host:
                        is_frag, _note = self.vl.confirm_absorption(
                            bgr, bb, ab)
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

    # ------------------------------------------------------------------
    # E1.5 VL 二次判定：候选漏斗 -> judge_view_candidates_v2 -> 三态合并
    # ------------------------------------------------------------------
    def vl_review(self, at):
        """对规则证据冲突的候选单元做 VL is_view 仲裁（2026-09 调研定稿）。

        送 VL 的三类触发（其余单元不送，候选率 <15%）：
          duplicate_serial   others 中读出与已绑定序号同值的数字（002 弯钩
                             误读 '7' 与已绑定序号'7'同值——分类错误直接导致
                             序号重复，必须仲裁）；
          big_digit_lowconf  lowconf 且读值为数字、maxdim>45（尺寸门卫拒收
                             但读值存疑的冲突单元，同 002 弯钩）；
          O_FACTOR 既有救援  build_atoms R1（已改走 judge_view_candidates_v2）。

        规则直判不送 VL：裸条元（长宽比>3.5 且墨迹面积<300px²）——孤立裸条
        无任何质感证据，多图验证中 VL 判定双向不稳定，维持现有归类。
        报警不自动判：小圆读值 '0'/'8'（round_serial_ambiguous）——圆形器物
        （铜钱/环/莲饰）与圆形字符在多图验证中双向混淆，一律转人工。

        三态合并：
          True  -> 回捞为视图（rescued_vl=True，墨迹掩膜，参与 E2~E5）；
          False -> 维持 others；
          None  -> 维持 + 报警 vl_verdict_unresolved（--strict-docx 停发）。

        判定明细写入 at["vl_review"]，报警写入 at["alarms_e15"] 并返回。
        """
        bgr = at["bgr"]
        binary = at["binary"]
        labels, others, views = at["labels"], at["others"], at["views"]
        alarms, review = [], []
        label_nos = {(s.get("no") or "").strip() for s in labels
                     if (s.get("no") or "").strip().isdigit()}
        if self.vl.enabled and others:

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
                # 尺寸下限：maxdim<12 的字形碎片（题注"1、6、"的断裂碎片、
                # 噪点）不具备回捞意义——验收门 h_>=12 同源；小碎片掩膜
                # 放大后墨迹发糊，VL 易误判为手绘（image298 '1、' 9×7 实测）
                w_, h_ = ob[2] - ob[0], ob[3] - ob[1]
                if max(w_, h_) < 12:
                    continue
                # 破折号+数字 debris（'1-1'/'—1'/'1–'）：刻度连接竖线/断裂符
                # 被 OCR 误读。管线对 serials 已有同型 tick_links 规则
                # （细高+含破折号→连接符不作标号），others 通道同型处理：
                # 不送 VL、不回捞（多图验证中此类裸条 VL 判定双向不稳定，
                # image722 曾 6/8 被误回捞）
                if re.fullmatch(r"[\d\s\-–—~∼.·lI]+", txt) \
                        and re.search(r"[\-–—~∼]", txt):
                    continue
                # 题注行（图注"1、瓷碗 2、银簪…"被 OCR 逐段读出）：数字开头
                # +分隔符+CJK 的读值必为图注文字，不送 VL（VL 对题注行判定
                # 不稳定——image431 同型判 False、image250 判 True 误回捞×4）
                if re.match(r"^\d{1,2}\s*[、.．,，：:]", txt) \
                        and re.search(r"[\u4e00-\u9fff]", txt):
                    continue

                # 细长杆歧义：所有有效连通域的 minAreaRect 长宽比>=3——
                # 竖直虚线段、断裂线、尺边被 OCR 拼成数字读值（image345
                # 'i1'、image420 '1'、image449 '1' 实测误回捞）。注意纯形状
                # 无法区分"手绘细长杆（真部件，簪针杆比率可达 13）"与
                # "虚线 debris"（多图验证'裸条不可判定'的回捞版），故不
                # 自动回捞也不静默丢弃，报警转人工。
                def _all_bar_like(box_):
                    """细长杆判据：单元 bbox 细长（>=3），或所有有效组件
                    的 minAreaRect 细长（>=3，覆盖多段短虚线拼成的单元）。"""
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
                    # duplicate_serial 仅收"大单元"（下限 24 与 R1 一致）：
                    # 序号数字本身高十余像素，与已绑定序号同值的小单元是
                    # 绑定/噪声问题而非漏网部件，回捞会产出假视图
                    # （image362 '2' 13×10、image76 '2' 21×11 实测误回捞）
                    cands.append({"bbox": list(ob), "src": "duplicate_serial",
                                  "reason": reason, "text": txt, "no": digit})
                    cand_pairs.append(oi)
            if cands:
                flags, _note = self.vl.judge_view_candidates_v2(
                    bgr, cands, context=f"E1.5 n={len(cands)}")
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
                            # 部件（002 J形小钩被读作'7'）从视图集无声移除，
                            # 下游连接符端点解析随之误配（002 [0,8] 混号根源
                            # 之一）——显性化转人工复核
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

    # ------------------------------------------------------------------
    # E1.5 复核标注图：把 VL 判定/报警画回原图（人工复核展示，不参与判定；
    # "标注原图作判定输入"已被多图实验证伪——41.3% vs 掩膜裁片 84.3%）
    # ------------------------------------------------------------------
    def write_vl_review_sheet(self, at, stem=None):
        import cv2 as _cv2
        bgr = at["bgr"]
        vis = (bgr.astype(np.float32) * 0.88 + 255 * 0.12).astype(np.uint8)

        def _tag(box, color, text, above=True):
            x0, y0, x1, y1 = [int(v) for v in box]
            _cv2.rectangle(vis, (x0, y0), (x1, y1), color, 2)
            ty = y0 - 4 if above else y1 + 13
            _cv2.putText(vis, text, (max(0, x0), max(13, ty)),
                         _cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1,
                         _cv2.LINE_AA)

        for v in at["views"]:                       # 绿：视图（含回捞）
            _tag(v["bbox"], (60, 180, 60),
                 f"V{v['id']}" + ("+VL" if v.get("rescued_vl") else ""))
        for s in at["labels"]:                      # 蓝：序号
            _tag(s["bbox"], (200, 120, 0), f"L{s.get('no', '')}")
        for s in at["scales"]:                      # 橙：比例尺
            _tag(s["bbox"], (0, 130, 255), "SCALE")
        for o in at["others"]:                      # 灰：维持 others
            _tag(o["bbox"], (128, 128, 128), "O", above=False)
        review = at.get("vl_review", [])
        for c in review:                            # 品红：VL 判定明细
            color = ((220, 0, 220) if c["verdict"] is True
                     else (0, 0, 220) if c["verdict"] is False
                     else (0, 60, 255))
            _tag(c["bbox"], color,
                 f"{c['src'][:12]}:{'T' if c['verdict'] else 'F'}")
        for a in at.get("alarms_e15", []):          # 红：E1.5 报警
            if a.get("bbox"):
                _tag(a["bbox"], (0, 0, 255), "ALERT", above=False)
        out_dir = os.path.join(self.out_root, stem or "vl_review")
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, f"{stem or 'vl_review'}_vl_review.png")
        _ok, buf = _cv2.imencode(".png", vis)
        buf.tofile(p)
        return p

    # ------------------------------------------------------------------
    # E2 序号 -> 视图归属（外侧优先：下/上/右/左；内部兜底）
    # ------------------------------------------------------------------
    def bind_labels(self, at):
        """序号绑定视图：收集全部候选 -> 全局贪心分配 -> 内部候选让位外部。

        R3 修复（相对旧版逐视图仲裁）：
          - 每个 label 收集全部可行视图候选（不再只留最优一个），全局按
            (rank, gap) 升序贪心：视图已被"异号"占据时该候选不可用，label
            自动尝试次优视图（被弃序号向次优视图迁移，而非直接丢弃）；
          - 同视图允许多个"同号"标号共存（同号多视图是 G1 分组依据）；
          - 内部候选（rank3）仅在最终该视图无任何外部标号时生效（修复旧版
            has_outside 全局集合把内部候选自己计入导致的"自我否决"bug）；
          - 左右两侧候选（rank2）收紧 gap 上限（max(30, 0.1*maxdim)）——
            相邻小视图不再轻易抢走本属大视图的序号（003 '1' 案例）。

        R3b 刚性竞争置信度驱逐（2026-09 E2 单独评估新增）：
          两个异号刚性标号（均无次优候选）竞争同一视图时，旧版按 (rank,gap)
          先到先得——image431 断裂符误读 '1'@conf0.5（gap2）压过真序号
          '2'@conf1.0（gap42），真序号丢失绑定。现允许挑战者驱逐"低置信
          在位者"（conf < evict_conf_floor 且挑战者 >= 在位者 +
          evict_conf_margin）；被驱逐者按冲突弃用留痕报警。弹性标号仍只
          迁移不驱逐（行为不变）。image166 断裂符 '7'@0.573 被真 '1'@0.991
          驱逐，同规则修复。
        R3c 空白角墨迹纠正（2026-09 E2 单独评估新增，ink_corner_fix）：
          序号印在视图 bbox 空白角（视觉在器物下方/上方，bbox 冗余把它包
          进去）时，bbox 级判定只能给 rank3 内部证据——被 G1 同号分组排除、
          异号迁移时易错选宿主（003 真 '1' 曾只能 inside 绑定）。现用二值
          墨迹做列向检查（标号所在列 ±2px、剔除标号自身墨迹）：墨迹仅在
          标号一侧且间隙 ≤ outside gap 阈值时，换算为该侧下/上外部关系
          （gap 以墨迹紧致边为基准）。守卫：① 同号存在更高置信者（低置信
          重复，如断裂符误读 image73 '7'@0.724）不做换算，维持 rank3 不参与
          G1；② 两侧均有墨迹（真在图形内部/旁侧）维持 rank3。无二值图
          （at["binary"] 为空）时整条规则自动旁路，行为同基线。

        E2.1 连接符继承（2026-09 E2 可用性调研新增，始终执行）：
          断裂符两端"一端有号、一端无号"时，无号视图继承有号视图的序号
          （002 V2 经"一"连 V1[号1] → V2 继承号1）。关联几何与 E3 G2 同源
          （横/竖向、轴向对齐 ±8、端向 gap ∈ [-8, link_gap]），差异仅在
          G2"同侧多匹配取后者"处改为取最近者（min |gap|——断裂符连接几何
          上最贴近的视图；002 '一'@554 左端 V0[g-22] vs V5[g3]，真邻 V5）。
          守卫：来源只认
          外部证据（rank<3）的直接绑定号（rank3 内部号多为拓片幻影，禁止
          经连接符传播）；目标视图必须无直接绑定号且未继承过（一跳）。
          继承号 v["label_ranks"] 记 4（不作 G1 同号证据，分组行为与无
          继承时完全一致——连接符分组仍由 E3 G2 完成，此处只把归属显式
          化），不写 label_boxes（该视图无印刷序号）。继承视图退出 G3 无号
          候选集（其组归属 G2 已给出）。调研：539 连接符中 433（80.3%）
          可继承，无号视图 541 -> 108，覆盖率 46.6% -> 90.7%。

        E2 单独评估（2026-09）：绑定全过程留痕 at["e2"]——逐 label 候选
        清单（view/rank/rel/gap）、最终归属（attach/rank/rel/gap）、未绑定
        原因（no_candidate/conflict_dropped/inner_yielded/invalid）、逐视图
        绑定结果、逐连接符分类（at["e2"]["links"]）与评估指标 metrics，
        供 --e2-only / --from-e1 产物落盘与 archea_show_e2.py 可视化；
        R3b/R3c 可经 ink_corner_fix / stiff_evict 开关整体回退到基线行为
        （A/B 见 _plan_tmp/ab_e2_opt.py）。
        """
        views = at["views"]
        view_by_id = {v["id"]: v for v in views}
        REL_NAME = {0: "below", 1: "above", 2: "side", 3: "inside"}

        def _outside_gap_th(vb):
            return max(self.p_label_gap, 0.12 * max(vb[2] - vb[0],
                                                    vb[3] - vb[1]))

        def _inside(box, vb):
            return vb[0] <= box[0] and box[2] <= vb[2] \
                and vb[1] <= box[1] and box[3] <= vb[3]

        binary = at.get("binary")

        def _ink_rel(box, vb):
            """R3c 空白角纠正：bbox 内标号的墨迹级下/上关系换算。

            序号印在视图 bbox 的空白角（视觉位于器物下方/上方，但 bbox 冗余
            把它包了进去）时，bbox 级判定只能给"内部"证据（rank3）——被 G1
            同号分组排除、且异号迁移时易错选宿主。用二值墨迹做列向检查：
            标号所在列（±2px）上、剔除标号自身墨迹后，若墨迹仅存在于标号的
            上方，则换算为下方外部关系（视觉在器物下方，gap 以墨迹紧致边为
            基准，仍须过 outside gap 阈值）。K2 业务规则：序号不会印在视图
            上方——墨迹仅在标号下方时不换算，返回 None 维持 rank3 兜底。
            两侧均有墨迹（真在图形内部/旁侧）或无二值图时返回 None。
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
            ly0 = max(0, int(box[1]) - 2 - vy0)      # 剔除标号自身墨迹（含 2px 余量）
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
            # 序号墨迹仅在下方（视觉在器物上方）不再换算为 above 关系——
            # 业务规则 K2：器物序号不会印在视图上方，该序号不属此视图；
            # 返回 None 维持 rank3 内部兜底（交由内部让位规则处置）
            return None

        # 1) 逐 label 收集全部候选 (rank, gap, view_id)
        cands = {}
        above_rej = {}                        # id(lb) -> 曾有上方关系被拒（K2）
        trace = []                            # E2 评估留痕（与 at["labels"] 对齐）
        # 同号最高置信（R3c 重复守卫用）：图内每序号通常只印一次
        # （解析说明.docx），低置信同号重复多为断裂符/纹理误读
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
                    # 下缘附近判定（兼容骑跨下缘的印刷位）；gap<0（序号与视图
                    # bbox 纵向交叠）时要求 x 向实际交叠——序号整体位于视图
                    # x 范围之外者不属此视图（003 '4'@672 落在 V6 框右下角
                    # 外缘，真宿主是其右上方 gap=3 的 V5）
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
                    if self.ink_corner_fix:
                        # R3c 重复守卫：同号存在更高置信者（低置信重复，如
                        # 断裂符误读）不做换算——维持 rank3 内部兜底（不参
                        # 与 G1 同号分组），防止 rank0 抢走真序号的视图
                        # （image73 '7'@0.724 曾压过真 '5'@1.0）
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

        # 2) 全局贪心分配：先"刚性"label（仅一个候选视图，无从让位——如 002
        # 的 '4' 只标在大钉下方），后"弹性"label 按 (rank, gap) 升序；视图被
        # 异号占据时弹性 label 自动迁移次优候选（'6' 让出大钉、绑到小钉）
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
                    # R3b 置信度驱逐：仅刚性标号（无次优候选可迁移）触发——
                    # 在位者 conf 低于 evict_conf_floor 且挑战者显著更高
                    # （>= 在位者 + evict_conf_margin）时，在位者按冲突弃用
                    # 让位（image431 断裂符误读 '1'@conf0.5 曾抢占真序号
                    # '2'@conf1.0 的唯一候选视图，致 '2' 丢失绑定）
                    if not (allow_evict and self.stiff_evict):
                        continue
                    inc = blockers[0]
                    inc_conf = inc.get("conf") or 0.0
                    cur_conf = lbs_by_id[lid].get("conf") or 0.0
                    if not (inc_conf < self.evict_conf_floor
                            and cur_conf >= inc_conf + self.evict_conf_margin):
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

        # 3.5) R7 同号唯一（业务规则 K1：一张线图上同一器物序号只印一次；
        # 例外位"比例尺左侧"已由 E1 归入 prefixes）：同一 no 有多个 serial
        # 获绑定时按 (rank, conf) 字典序择优保留一个（方位更标准者优先，
        # 同方位比置信度），其余弃用留痕报警。多视图共享序号走 E2.1 断裂
        # 符继承（rank4，不在本步约束范围）。
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
        #    无号视图继承有号视图的序号（002 V2 经"一"连 V1[号1] → V2 继承
        #    号1）。调研（_plan_tmp/e2_link_study.py，159 图）：539 连接符中
        #    433（80.3%）为继承候选，无号视图 541 -> 108，覆盖率 46.6% ->
        #    90.7%，全部一跳。关联几何与 E3 G2 同源（横/竖向、轴向对齐
        #    ±8、端向 gap ∈ [-8, link_gap]），同侧多匹配取最近者（min |gap|，
        #    见方法 docstring）。连接符来源含 R5 恢复（from-e1 复现模式下
        #    按现行规则从 others 重建被旧版 bbox 级过滤误删的断裂符）。
        direct = {v["id"]: list(v["label_nos"]) for v in views}  # 直接绑定快照
        # 来源守卫：只认外部证据（rank<3）的直接绑定号——rank3 内部号多为
        # 拓片纹理 OCR 幻影（image76 银币内圈幻影 '3'），经连接符传播会把
        # 幻影挂到更多视图。调研 433 个继承来源全部为外部证据（守卫零削减）。
        src_ext = {}
        for v in views:
            src_ext[v["id"]] = list(dict.fromkeys(
                no for no, rk in zip(v["label_nos"], v["label_ranks"])
                if rk < 3))
        got = set()                                   # 已继承视图（一次）
        link_trace = []
        n_inherited = 0
        binary = at.get("binary")
        for lk in at.get("links", []):
            b = lk["bbox"]
            A, B = self._resolve_link_ends(views, b, binary)
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

        # 继承号语义（结构性约定，非开关）：
        #   - v["label_ranks"] 记 4：G1 同号分组只认外部证据（rank<3），继承
        #     号不作同号证据——分组行为与无继承时完全一致（连接符分组仍由
        #     E3 G2 完成，此处只把归属显式化）；继承视图退出 G3 无号候选集
        #     （其组归属 G2 已给出，G3 吸附本就冗余）；
        #   - 不写 v["label_boxes"]（该视图并无印刷序号，E5 描字剔除、
        #     overlay 画框均不受影响）。

        # 6) E2 评估留痕：逐视图绑定 + 指标（判定不变，仅记录）
        def _numkey(s):
            return (0, int(s)) if s.isdigit() else (1, s)

        nos_bound = {}
        for vid, ids in direct.items():               # 仅直接绑定（不含继承）
            for no in ids:
                nos_bound.setdefault(no, set()).add(vid)
        serial_set = (at.get("rec") or {}).get("serial_set") or {}
        set_nums = {str(x) for x in serial_set.get("nums", [])}
        # 救援序号并入序号集口径（与全流程 extract_image 的 _ss 合并一致）：
        # 'i'/'l'→'1' / E2.5 VL 补读的序号不在 rec.serial_set 里，否则会产生
        # 假"绑定号不在序号集"报告（image160/236/238/261 的救援 '1'）
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
            # 视图覆盖口径：labeled/unlabeled 均只计直接绑定；继承见 *_after
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
            "params": {"label_gap_max": self.p_label_gap,
                       "side_gap_cap": "max(30, 0.1*maxdim)",
                       "inner_yields_to_outside": True,
                       "ink_corner_fix": self.ink_corner_fix,
                       "stiff_evict": self.stiff_evict,
                       "evict_conf_floor": self.evict_conf_floor,
                       "evict_conf_margin": self.evict_conf_margin,
                       "link_inherit": "always-on (E2.1, rank4 evidence)",
                       "greedy": "stiff-first(evict-able) then (rank,gap) flex",
                       "above_candidates": "rejected (K2: 器物序号只在视图下侧)",
                       "serial_unique": "R7: 同号多绑按 (rank,conf) 择优留一 (K1)",
                       "scale_side_serials": "routed to prefixes (K1 例外位)"},
            "labels": trace,
            "links": link_trace,
            "metrics": metrics,
        }

    # ------------------------------------------------------------------
    # 连接符端点解析（E2.1 继承与 E3 G2 共用）
    # ------------------------------------------------------------------
    def _resolve_link_ends(self, views, b, binary=None):
        """断裂符 bbox -> (上/左端视图, 下/右端视图) 各至多一个。

        候选收集（G2 原窗口 + 端点包含）：
          - 轴向对齐 ±8、端向 gap ∈ [-8, link_gap]（G2 原窗口）；
          - 或视图 bbox 在关联轴上包含该端点（断裂符印在视图 bbox 空白角/
            视图间隙——002 '一'@554 整体落在 V6 框内，纯窗口会漏掉真邻）。
        多候选解析（墨迹级，R5）：
          - 端向墨迹距离：在连接符行/列带内、排除连接符自身墨迹后，视图
            朝向连接符一侧的最近墨迹到连接符的距离；墨迹在错误一侧（负距
            离）视为不候选——大 bbox 层叠吞入邻域时 bbox gap 会误判
            （002 '一'@554：左端 V0[g-22] vs V5[g3]，右端 V6[g-32] vs
            V4[g15]，bbox 级怎么选都错）；
          - 带内无墨迹：退回 bbox |gap|；
          - 距离并列：取不包含对方 bbox 的更"局部"视图（V0 大框常含 V5，
            并列时 V5 才是真邻）。
        binary 为空（理论不发生）时退回纯 bbox |gap|。
        """
        H = W = 0
        if binary is not None:
            H, W = binary.shape[:2]
        gap_max = self.p_link_gap
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
                # 唯一包含候选盲采否决（002 教训）：端点落在 bbox 内部且无
                # 窗口邻接候选时——真目标在场上（如小钩已回捞）则会有多候选
                # 走相对择优；只剩一个包含候选往往意味着真目标缺失、当前
                # 候选只是几何上罩住端点的大框。校验其掩膜最近墨迹：距离
                # > link_gap 视为无证据，拒绝（端空，宁缺勿错）。
                # 多候选端不否决：相对择优（墨迹/bbox gap）本就安全。
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

    def _extend_link_end(self, views, b, binary, exclude_ids, empty_end,
                         text=""):
        """S4 连接符轴线延伸：单端已解析、另一端为空时，沿连接符主轴向空端
        延伸找对端视图。

        护栏（评审核实 image187/196 误并后加入）：
          - 数字文本拒绝：text 为 1~2 位数字的"连接符"实为被 E1 误判的印刷
            序号数字（187 '一'实为'1'、196 文本'1'），延伸会放大该误判，
            直接不延伸；
          - 墨距上限：墨距 <= max(1.6*link_gap, 2.0*连接符长)——延伸只为
            覆盖窗口边界附近的错位排版（194 实例 58px），187 跳 288px 拉进
            异器物、196 越过未分割截面图远跳 87px，均须拒绝。

        候选硬约束（全部满足）：
          - 主轴（连接符中线）与视图 bbox 相交（轴向对齐 ±8，与
            _resolve_link_ends 的轴窗口同口径）——轴线相交是图形对应关系，
            非距离阈值匹配，符合规范"按连接符图形对应"口径；
          - 视图位于空端一侧（竖符：上/下方；横符：左/右侧）；
          - 不与已解析端同组（exclude_ids 传入已解析端视图 id）。
        择端：带内墨迹距离最近者（连接符行/列带内、排除连接符自身墨迹后
        视图朝向侧最近墨迹到连接符端的距离；墨迹缺失/在错误一侧不候选——
        无墨迹证据不延伸，严禁纯几何猜测）。返回 (view_id, 墨距) 或 None。
        """
        H, W = binary.shape[:2]
        vertical = (b[3] - b[1]) >= (b[2] - b[0])
        lo_end, hi_end = (b[1], b[3]) if vertical else (b[0], b[2])
        conn_len = (b[3] - b[1]) if vertical else (b[2] - b[0])
        if text.isdigit() and len(text) <= 2:
            return None                          # 印刷序号数字误判为连接符
        d_cap = max(1.6 * self.p_link_gap, 2.0 * conn_len)
        best = None
        for v in views:
            if v["id"] in exclude_ids:
                continue
            vb = v["bbox"]
            if vb[0] <= b[0] and b[2] <= vb[2] \
                    and vb[1] <= b[1] and b[3] <= vb[3]:
                continue      # 视图包含连接符：是"容器"不是延伸目标（002 大框）
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
            # 带内墨迹距离（_resolve_link_ends._ink_dist 同口径，但排除方向
            # 按几何正确实现：竖符在视图 y 带内排除连接符自身"行"段，横符
            # 在连接符 y 带内排除连接符自身"列"段）
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

    # ------------------------------------------------------------------
    # E2.5 序号漏检 VL 补救（S2 补救场景一）：OCR 漏读的正文序号无法凭空
    # 找回，但其印刷体单元往往仍在 others 里（lowconf/unreadable/tiny）。
    # 对"疑似序号形态 + 紧邻某视图"的此类单元批量裁片送 VL 复读，读出
    # 恰为缺失序号且可归位相邻视图的，补挂绑定（rank2 外部证据）。
    # ------------------------------------------------------------------
    def rescue_missing_serials(self, at):
        """返回补救成功的序号数。VL 禁用/无缺失/无候选时为 0。"""
        if not self.vl.enabled:
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
                # K2 业务规则：序号不会在视图上方——rescue 不再采上方关系
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
        crops = [self.vl._crop(at["bgr"], o["bbox"], pad=4) for o, _v in cands]
        reads, _note = self.vl.read_serial_crops(
            crops, context=f"missing={sorted(missing)}")
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

    # ------------------------------------------------------------------
    # E3 视图分组（G1 同号 > G2 连接符 > G3 竖栈/横行 > VL 兜底）
    # ------------------------------------------------------------------
    def group_views(self, at):
        views = at["views"]
        n = len(views)
        uf = UnionFind(n)
        merge_log = []
        # E3 评估留痕（无行为影响）：逐规则合并计数 + VL 触点统计。
        # vl_touchpoints 记录"将触发 VL 仲裁/把关的决策点"次数——VL 关闭
        # （--no-vl / from-e1 桩）时照样计数，用于估算纯 CV 迭代与 VL 全量
        # 之间的行为差和调用成本。
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
        # 幻觉（image76 银币上枚内部一排幻影 '3'/'6'/'2'/'7'），不得借 G1
        # 把异器物连锁并组。build_atoms 里 label_ranks 初始化为 []。
        by_no = {}
        for v in views:
            for no, rank in zip(v["label_nos"], v.get("label_ranks", [])):
                if rank < 3:
                    by_no.setdefault(no, []).append(v["id"])
        for no, ids in by_no.items():
            for k in range(1, len(ids)):
                merge(ids[0], ids[k], "G1_same_label", f"no={no}")

        # G2 连接符：短竖/横线两端视图相连（端点解析与 E2.1 共用
        # _resolve_link_ends——同侧多匹配取最近墨迹，修复旧版"后者覆盖"
        # 以及 R5 恢复断裂符落在大视图框内时误关联远处视图的问题）
        _g2_binary = at.get("binary")
        for lk in at["links"]:
            b = lk["bbox"]
            end_a, end_b = self._resolve_link_ends(views, b, _g2_binary)
            if end_a and end_b:
                merge(end_a[0], end_b[0],
                      "G2_connector_v" if (b[3] - b[1]) >= (b[2] - b[0])
                      else "G2_connector_h", str(b))
                continue
            # S4 轴线延伸：单端已解析、另一端为空时，沿连接符主轴向空端延伸，
            # 取"主轴与 bbox 相交 + 位于空端一侧 + 带内墨迹校验通过"的最近
            # 视图补足对端。轴线相交是硬约束而非距离阈值（符合规范"序号/
            # 连接符图形对应"口径），修复错位排版下端向窗口卡死——
            # image194 '一'@[702,262,708,295] 上端 gap=55 恰超 link_gap 3px
            # 导致单端解析不并、细节视图孤立。
            if (end_a or end_b) and _g2_binary is not None:
                stats["s4_ext_attempt"] += 1
                empty = "a" if not end_a else "b"
                taken = ([end_a[0]] if end_a else []) \
                    + ([end_b[0]] if end_b else [])
                hit = self._extend_link_end(
                    views, b, _g2_binary, taken, empty,
                    text=(lk.get("text") or "").strip())
                if hit is not None:
                    vid, d_ext = hit
                    fixed = (end_a or [vid])[0]
                    partner = (end_b or [vid])[0]
                    stats["s4_ext_merged"] += 1
                    merge(fixed, partner,
                          "G2_connector_v_ext" if (b[3] - b[1]) >= (b[2] - b[0])
                          else "G2_connector_h_ext",
                          f"轴线延伸 墨距={d_ext} {b}")

        # S1 规则B连通分量闸（评审修订版）：全图无外部绑定序号（rank<3，
        # 视图内部号/继承号不算硬证据）且视图数 >1 时，若 G1/G2 硬证据连接
        # 图的连通分量 >=2，说明图面呈现多个独立器物单元——按规范第二篇
        # 第4条"无序号多物体图必须触发报警待人工复核，严禁强制配对或猜测
        # 配对"：跳过 G3/G4 几何吸附与 G0 全并，仅保留硬证据组合并输出报警
        # （image143 两条 G2 链分属两件钱币；image251 平剖面+垃圾视图）。
        # 分量=1（image13/244 单连接符链）保持原路径不变。
        # 注：分量须在 G3 之前按 G1/G2 边计（评审核实：143 被 G3_row 桥接
        # 后已并关系只剩 1 个分量，G3 之后计算会漏报）。
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

        # S2 完整视图守卫（评审校准版）：G3/G4 的 row/stack 几何自动并，若
        # 合并侧视图为"完整视图"（bbox 面积 >= 0.5*全图视图面积中位数——
        # 天然细长的完整器物如骨锥/骨匕首按面积判定，不再豁免细长条）且其
        # 就近（<=label_gap）存在被 E2 丢弃/落选的序号信号（该器物本应有号
        # 却无号，几何吸附极易过并——image449 被丢的 '1' 恰落在骨锥 V2 上，
        # 被并入号2 组），降级为 VL 确认；VL 关闭 -> hold 不并并记待复核。
        # 双条件缺一不可：image264 链条节段（面积过半但无丢弃号信号）、
        # image722 石器配对（完整视图但序号无争议）均不受影响，保持自动并。
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
                if max(gx, gy) <= self.p_label_gap:
                    return True
            return False

        def guard_needed(vid):
            return complete_ish(vid) and suspect_serial_near(vid)

        # G3 无标号组迭代吸附（R4 修复：旧版"单例一次性贪心+并组即冻结"使
        # image264 的链条组与主体永无合并机会；改为逐轮评估"无标号组 -> 任意
        # 组"的最近成员对，直至收敛。候选按组内成员视图逐个判定——禁止用组
        # 并集大框制造虚假相邻；bbox 浅相交（交叠 < 0.5*较小面积）且目标组
        # 带标号时须 VL 确认（防 003 波浪条/大骨器尖端互伸的假 touch 误并）。
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
            if gy > 0 and gy <= self.p_stack_gap:
                xov = bbox_hov(ub, mb) / max(1, min(ub[2] - ub[0],
                                                    mb[2] - mb[0]))
                if xov >= self.p_stack_xov:
                    return ("stack", gy)
            elif gx > 0 and gx <= self.p_row_gap:
                yov = bbox_vov(ub, mb) / max(1, min(ub[3] - ub[1],
                                                    mb[3] - mb[1]))
                if yov >= self.p_row_yov:
                    return ("row", gx)
            return None

        def try_merge(uid, gi, rels):
            """uid 组并入 gi 组：组内候选关系按 gap 升序逐个尝试（rels 元组
            为 (rule, gap, gi侧成员, uid侧成员)；VL 裁片取实际产生该关系的
            uid 侧成员，而非发起视图自身）；
            touch_shallow 且目标带标号时须 VL 把关，VL 拒后回退组内下一关系
            （image134 横条剖面与 3 号主图 stack 77、与柄部 touch_shallow）；
            目标无标号的 touch_shallow 直接并（264 链条节段互叠 0.086 依赖它）。"""
            tgt_has_label = any(views[i]["label_nos"] for i in group_members(gi))
            for rule, gap, m, ui in sorted(rels, key=lambda r: r[1]):
                if rule == "touch_shallow":
                    if not tgt_has_label:
                        stats["g3_touch_shallow_merge"] += 1
                        merge(uid, m, "G3_touch_shallow", f"gap={gap}")
                        return True
                    stats["g3_touch_shallow_vl"] += 1
                    stats["vl_touchpoints"] += 1
                    same, vl_note = self.vl.same_artifact(
                        at["bgr"], views[ui]["bbox"], views[m]["bbox"])
                    if not same:
                        continue              # VL 拒：尝试组内下一关系
                    stats["g3_touch_shallow_vl_merged"] += 1
                    merge(uid, m, "G3_touch_shallow_vl", vl_note)
                    return True
                # 远间隙行并降级：合法 row 合并实测最大 gap=97（389），134 的
                # 109 是唯一超限案例且为误并——auto_max < gap <= row_gap_max
                # 区间不再纯几何自动并，降级 VL 确认（VL 关 -> hold 保持独立）
                if rule == "row" and gap > self.p_row_auto_max:
                    stats["g3_row_far_touchpoints"] += 1
                    stats["vl_touchpoints"] += 1
                    same, vl_note = self.vl.same_artifact(
                        at["bgr"], views[ui]["bbox"], views[m]["bbox"])
                    if not same:
                        stats["g3_row_far_holds"] += 1
                        merge_log.append({
                            "rule": "G3_row_far_hold", "views": [ui, m],
                            "note": f"远间隙行并 gap={gap}>"
                                    f"{self.p_row_auto_max} 未获VL确认"
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
                    same, vl_note = self.vl.same_artifact(
                        at["bgr"], views[ui]["bbox"], views[m]["bbox"])
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
                # 组级候选关系：uid 自身关系全类型参与（与旧口径一致）；组内
                # 其他成员仅代理"相交类强证据"（touch/touch_shallow——接触面
                # 属于整个组）。stack/row 弱邻近不代理：细长视图嵌套会造出
                # xov=1 的伪 stack（image263 V4-V12 实证，号5部件险被号6抢并）。
                # image134：发起组{2,6}的 V6 与带号'3'的 V7 touch_shallow(0)，
                # uid=V2 自身与{7}无关系（gy=104 超 stack 窗），代理后 {7} 以
                # dominance 胜出——旧口径只剩远列 row(109) 的{0,8}致号3被拆。
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
                    # 多候选歧义：VL 兜底裁决（分别与最近两组的成员视图成对判断，
                    # 裁片取实际产生最近关系的 uid 侧成员；VL 均否/不可用 ->
                    # 放弃合并，保持独立并记录待复核）
                    stats["g3_ambiguous"] += 1
                    stats["vl_touchpoints"] += 2
                    (g1, rels1), (g2, rels2) = ordered[0], ordered[1]
                    m1, u1 = min(rels1, key=lambda r: r[1])[2:4]
                    m2, u2 = min(rels2, key=lambda r: r[1])[2:4]
                    same1, note1 = self.vl.same_artifact(
                        at["bgr"], views[u1]["bbox"], views[m1]["bbox"])
                    same2, note2 = None, ""
                    if same1 is not True:
                        same2, note2 = self.vl.same_artifact(
                            at["bgr"], views[u2]["bbox"], views[m2]["bbox"])
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
                        merge_log.append({"rule": "G3_vl_abandon", "views": [uid],
                                          "note": f"多候选歧义放弃: {note1} | {note2}"})

        # G4 带号单例视图吸附无标号组（R5 修复：序号只标在器物某一个视图上时，
        # 其余视图已自成无号组——带号视图须把紧邻的无号组吸回来，组号随之覆盖
        # 全组。image121 碗底内面('1')与碗主体组 gap=2、image264 链条组与带号
        # 主体 gap=9 均属此类。阈值比 G3 严：gap<=30、重公布>=0.5，多候选 VL）。
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
                        same, vl_note = self.vl.same_artifact(
                            at["bgr"], views[v["id"]]["bbox"],
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
                    same1, note1 = self.vl.same_artifact(at["bgr"], ub,
                                                         views[m1]["bbox"])
                    same2, note2 = None, ""
                    if same1 is not True:
                        same2, note2 = self.vl.same_artifact(at["bgr"], ub,
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

    # ------------------------------------------------------------------
    # E4 比例尺绑定（L1 前缀硬匹配 > L2 唯一尺共享 > L3 VL 兜底 > 放弃）
    # ------------------------------------------------------------------
    def bind_scales(self, at, groups):
        """返回 (group_scales: [ [ {scale, source, prefix_nos, shared} ] ],
        scale_records, alarms)。绑定严禁坐标距离：只用前缀序号文本。"""
        scales = at["scales"]
        prefix_nos_of = []

        def expand_prefix_nums(text):
            """前缀序号集合：支持连续列举（'1、2.'、'3、4.'）与范围
            （'1~7.'、'8~11.'，范围跨度<=30 防误扩）。"""
            nums = set()
            t = text or ""
            for m in re.finditer(r"(\d{1,2})\s*([~～\-—–])\s*(\d{1,2})", t):
                a, b = int(m.group(1)), int(m.group(3))
                if 0 < a <= b <= a + 30:
                    nums.update(range(a, b + 1))
            nums.update(int(x) for x in re.findall(r"\d{1,2}", t))
            return nums

        def scale_prefix_nums(si):
            """比例尺前缀序号集合：尺行前缀序号（含跨 token 范围，如 '1'+'~'+'7.'
            被 OCR 拆成两单元——两 token 间隙有墨迹即判定为范围 a~b 并展开）+
            raw_text 前缀段。绑定严禁坐标距离，只用序号文本证据。"""
            bb = scales[si].get("bar_bbox") or scales[si]["bbox"]
            band_top = bb[1] - 12
            band_dn = bb[3] + 12
            ext = self.rec.p["prefix_ext"]
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
                # 间隙墨迹形态判定（R6 修复）：对间隙做连通域分析，取最大前景
                # 域——仅"居中横条"（～/—/–，垂直中心位于 token 高度 <=0.8 处、
                # 宽 >=4px 且高 <=0.7 倍 token 高）视为范围符并展开 a~b；
                # 底部小点（、，实测垂直中心 ~0.9）只证明列举关系，严禁展开
                # （'1、5、6.' 曾被展开成 1~5、'4.'+'7' 曾被展开成 4~7）。
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
            # 前缀兜底（R6 收紧）：整段前缀（如 '1~3.'）被 OCR 低置信丢弃进 others
            # 时，吸收与本尺已收 token 水平相邻（间隙<=20px）的可信单元：
            # scale_zone 是已证认的尺上杂物（起点 0 幻觉等，130 右尺曾混入），
            # 不采信；lowconf 单元有真有假——紧贴 token（间隙<8px）的小点是
            # 列举符 '、' 的幻觉读值（264 右尺幻觉 '1.'），间距正常的是真前缀
            # 碎片（261 '1、2、3' 等），按间隙区分
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
                    # lowconf 紧贴已收 token（间隙<8px）的小点是列举符 '、' 的
                    # 幻觉读值（264 右尺幻觉 '1.'）；本尺 row 为空时无附着对象，
                    # lowconf 整段前缀（261 '1~4.'）恰是兜底要救的目标，放行
                    if o.get("reason") == "lowconf" and toks and near < 8:
                        continue
                    # 范围碎片展开（132 修复）：'2~5.' 被 OCR 拆成 token '2' +
                    # 碎片 '~5.' 时，范围符与右端落在碎片里、左端在已收 token
                    # 上——按"左邻 token 号 ~ 碎片右端号"补全展开 2~5 -> {2..5}
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
            # （18 右尺 row={3,4} 而粘连段给 '1'，属粘连幻觉）
            pv_nums = expand_prefix_nums(pv.get("prefix") or "")
            row_nums = {x for _b, ns in toks for x in ns}
            if not toks or (pv_nums & row_nums):
                nums |= pv_nums
            return nums

        for si in range(len(scales)):
            prefix_nos_of.append(scale_prefix_nums(si))

        # L1.5 前缀漏检 VL 补救（S2 补救场景二）：规则收集后仍无前缀的尺
        # （整段前缀被 OCR 漏读/粘连损毁），送 VL 读尺行前缀补齐——避免其
        # 直接滑落 L2 共享或 L3 造成 group_no_scale。VL 结果并入后按 L1
        # 同一方式参与硬匹配（匹配逻辑不变，仍严禁坐标距离）。
        vl_assisted = {}
        if self.vl.enabled and len(scales) > 1:
            # 仅多尺图触发：单尺图本就无前缀标注（L2 唯一共享天然覆盖），
            # 对其调 VL 是纯浪费（v6 实测曾多打 100 次）
            for si in range(len(scales)):
                if prefix_nos_of[si]:
                    continue
                nums, note = self.vl.read_scale_prefix(
                    at["bgr"], scales[si], where="scale_prefix")
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
                nums, note = self.vl.read_scale_prefix(at["bgr"], scales[si])
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
                        "scale_id": si, "note": note})
            scale_records.append(rec)

        # 组无任何比例尺 -> 报警（VL 已在 L3 尝试过全部未绑尺）
        for gi in range(len(groups)):
            if not bound[gi]:
                alarms.append({"code": "group_no_scale",
                               "msg": f"⚠ 报警：器物组{gi} 未绑定任何比例尺",
                               "group": gi})
        return bound, scale_records, alarms

    # ------------------------------------------------------------------
    # E5 组装输出（白底画布 + 原像素掩膜粘贴；视图相对关系原样；比例尺置底）
    # ------------------------------------------------------------------
    def compose_group(self, at, group_ids, bound_scales, seq_tag):
        """单组组装。返回 (png_bgr|None, group_record)。

        画面 = 视图填充 + 连接符 + 贴近说明文字；比例尺行 = 尺体+0+值文本。
        序号数字与比例尺前缀默认不画（strip_serial_digits / strip_scale_prefix），
        其 bbox 仍记入 members/scales 供追溯。"""
        bgr, binary = at["bgr"], at["binary"]
        views = [at["views"][i] for i in group_ids]
        H, W = bgr.shape[:2]

        # --- 成员掩膜收集（视图 + 标号 + 连接符 + 贴近说明文字） ---
        other_ids = [i for i in range(len(at["views"])) if i not in group_ids]
        other_mask = np.zeros((H, W), bool)
        for i in other_ids:
            m = at["views"][i].get("mask")
            if m is not None:
                other_mask |= m

        content_masks = []
        members = {"views": [], "labels": [], "links": [], "texts": []}
        cm = np.zeros((H, W), bool)
        for v in views:
            if v.get("mask") is not None:
                m = v["mask"] & ~other_mask          # 剔除其它组视图像素（防串染）
                if m.any():
                    content_masks.append(m)
                    cm |= m
                    members["views"].append({"id": v["id"], "bbox": v["bbox"]})
        if not content_masks:
            # 防串染剔除把整组清空（嵌套视图被 S1 硬证据闸分成两组等，
            # image251 平剖面图小视图完全落在大视图掩膜内）：回退原始掩膜，
            # 保持出图（该类图已带 S1/孤立报警，供人工复核）。
            for v in views:
                if v.get("mask") is not None:
                    cm |= v["mask"]
                    members["views"].append({"id": v["id"], "bbox": v["bbox"]})
            if cm.any():
                content_masks.append(cm.copy())
        for v in views:
            for lbbox in v["label_boxes"]:
                if self.strip_serial_digits:
                    # 序号数字只用于分组/绑定，不画进成品；bbox 仍记录可追溯
                    members["labels"].append({"bbox": lbbox, "painted": False})
                    continue
                m = ink_mask(binary, lbbox)
                if m is not None and m.any():
                    content_masks.append(m)
                    cm |= m
                    members["labels"].append({"bbox": lbbox, "painted": True})
        gbox0 = union_box([v["bbox"] for v in views])

        # 组内连接符
        gid = set(group_ids)
        for lk in at["links"]:
            b = lk["bbox"]
            touch = False
            for i in group_ids:
                gx, gy = bbox_gap(b, at["views"][i]["bbox"])
                if gx == 0 and gy == 0:
                    touch = True
                elif gx <= self.p_link_gap and gy <= self.p_link_gap:
                    touch = True
                    break
            between = False
            for i in gid:
                for j in gid:
                    if i >= j:
                        continue
                    bi, bj = at["views"][i]["bbox"], at["views"][j]["bbox"]
                    ib = union_box([bi, bj])
                    if ib[0] - 8 <= b[0] and b[2] <= ib[2] + 8 \
                            and ib[1] - 8 <= b[1] and b[3] <= ib[3] + 8:
                        between = True
            if touch or between:
                m = ink_mask(binary, b)
                if m is not None and m.any():
                    content_masks.append(m)
                    members["links"].append({"bbox": b, "text": lk.get("text", "")})

        # 贴近说明文字（图旁注释；远离的图注行不收）
        content_box = paste_region(cm)[0] or gbox0
        for o in at["others"]:
            if o["reason"] not in ("text", "unreadable"):
                continue
            ob = o["bbox"]
            gx, gy = bbox_gap(ob, content_box)
            if (gx == 0 and gy <= self.p_attach_gap) or \
                    (gy == 0 and gx <= self.p_attach_gap):
                m = ink_mask(binary, ob)
                if m is not None and m.any():
                    content_masks.append(m)
                    cm |= m
                    members["texts"].append({"bbox": ob, "text": o.get("text", "")})

        if not content_masks:
            return None, {"error": "no member masks"}

        content_box, content_sub = paste_region(cm)

        # --- 比例尺整组（尺体+0+值文本，默认不含左侧前缀序号）裁为底部行 ---
        scale_tiles = []
        for b in bound_scales:
            s = at["scales"][b["si"]]
            boxes = [s["bbox"]]
            for mem in s.get("members", []):
                boxes.append(mem["bbox"])
            if not self.strip_scale_prefix:
                for pr in at["prefixes"]:         # 旧行为：前缀序号随尺输出
                    pb = pr["bbox"]
                    bb = s.get("bar_bbox") or s["bbox"]
                    if pb[3] >= bb[1] - 12 and pb[1] <= bb[3] + 12 \
                            and bb[0] - self.rec.p["prefix_ext"] <= pb[2] <= bb[0] + 6:
                        boxes.append(pb)
            ub = union_box(boxes)
            sm = np.zeros((H, W), bool)
            mm = ink_mask(binary, ub, pad=1)
            if mm is not None:
                sm |= mm
            tb, tm = paste_region(sm)
            if tb is not None:
                scale_tiles.append({"box": tb, "mask": tm,
                                    "si": b["si"], "source": b["source"],
                                    "text": s.get("text", ""),
                                    "shared": b.get("shared", False)})

        # --- 画布：内容原样平移 + 比例尺置底（不缩放/不旋转/不重排） ---
        cw = content_box[2] - content_box[0]
        ch = content_box[3] - content_box[1]
        margin = max(6, int(round(self.margin_pct * max(cw, ch))))
        row_w = sum(t["box"][2] - t["box"][0] for t in scale_tiles) \
            + max(0, 2 * margin * (len(scale_tiles) - 1))
        row_h = max((t["box"][3] - t["box"][1] for t in scale_tiles), default=0)
        gap = margin if scale_tiles else 0
        Wc = max(cw, row_w) + 2 * margin
        Hc = margin + ch + gap + row_h + margin
        canvas = np.full((Hc, Wc, 3), 255, np.uint8)
        dx, dy = margin - content_box[0], margin - content_box[1]
        ys, xs = np.nonzero(content_sub)
        canvas[ys + margin, xs + margin] = \
            bgr[ys + content_box[1], xs + content_box[0]]
        # 像素一致性自检：内容区应为纯平移（无缩放/无旋转）——逐像素比对
        mismatch = int((canvas[ys + margin, xs + margin]
                        != bgr[ys + content_box[1], xs + content_box[0]])
                       .any(axis=-1).sum())

        # 比例尺行：原顺序左->右，水平居中
        xcur = margin + max(0, (max(cw, row_w) - row_w) // 2)
        ycur = margin + ch + gap
        tiles_out = []
        for t in scale_tiles:
            tw, th = t["box"][2] - t["box"][0], t["box"][3] - t["box"][1]
            tys, txs = np.nonzero(t["mask"])
            canvas[tys + ycur, txs + xcur] = \
                bgr[tys + t["box"][1], txs + t["box"][0]]
            tiles_out.append({"si": t["si"], "text": t["text"],
                              "source": t["source"], "shared": t["shared"],
                              "placed_at": [int(xcur), int(ycur),
                                            int(xcur + tw), int(ycur + th)]})
            xcur += tw + 2 * margin

        rec = {
            "seq": seq_tag,
            "label_nos": sorted({no for v in views for no in v["label_nos"] if no}),
            "members": members,
            "stripped": {"serial_digits": self.strip_serial_digits,
                         "scale_prefix": self.strip_scale_prefix},
            "content_src_box": content_box,
            "content_paste_at": [margin, margin],
            "translation": [int(dx), int(dy)],
            "pixel_mismatch": mismatch,
            "scales": tiles_out,
            "canvas_size": [int(Wc), int(Hc)],
        }
        return canvas, rec

    # ------------------------------------------------------------------
    # E1-only 分阶段评估结果（E2~E5 停用时的落盘与摘要）
    # ------------------------------------------------------------------
    def _e1_result(self, image, stem, at, t0, vl0):
        """原子收集产物序列化落盘 <stem>_e1.json（视图带掩膜裁片 base64；
        无分组/绑定/组装），供独立可视化脚本 archea_show_e1.py 展示评估；
        返回轻量摘要以兼容既有 CLI 打印与 batch_summary。"""
        import base64
        bgr = at["bgr"]
        H, W = bgr.shape[:2]

        def crop_b64(mask):
            """掩膜 -> (紧致bbox, 白底掩膜裁片 PNG base64)；空掩膜返回空。"""
            if mask is None or not mask.any():
                return None, None
            box, sub = paste_region(mask)
            crop = np.full((sub.shape[0], sub.shape[1], 3), 255, np.uint8)
            crop[sub] = bgr[box[1]:box[3], box[0]:box[2]][sub]
            _ok, buf = cv2.imencode(".png", crop)
            return box, base64.b64encode(buf.tobytes()).decode("ascii")

        views = []
        for v in at["views"]:
            cbox, cb64 = crop_b64(v.get("mask"))
            views.append({"id": v["id"], "bbox": v["bbox"], "area": v["area"],
                          "rescued": bool(v.get("rescued")),
                          "rescued_vl": bool(v.get("rescued_vl")),
                          "label_nos": list(v["label_nos"]),
                          "crop_box": cbox, "crop_base64": cb64})

        def ser_serial(s):
            return {"bbox": s["bbox"], "text": s.get("text", ""),
                    "no": s.get("no", ""), "conf": s.get("conf"),
                    "rotated": bool(s.get("rotated")),
                    "scale_prefix": bool(s.get("scale_prefix")),
                    "rescued": bool(s.get("rescued")),
                    "_vl_rescued": bool(s.get("_vl_rescued"))}

        scales = [{"kind": s.get("kind"), "orientation": s.get("orientation"),
                   "bbox": s["bbox"], "bar_bbox": s.get("bar_bbox"),
                   "text": s.get("text", ""), "raw_text": s.get("raw_text", ""),
                   "value": s.get("value"), "unit": s.get("unit"),
                   "conf": s.get("conf"), "verified": s.get("verified", True),
                   "ticks": s.get("ticks")} for s in at["scales"]]
        others = [{"bbox": o["bbox"], "reason": o.get("reason", ""),
                   "text": o.get("text", ""), "conf": o.get("conf")}
                  for o in at["others"]]

        out_dir = os.path.join(self.out_root, stem)
        os.makedirs(out_dir, exist_ok=True)
        data = {
            "ok": True, "stage": "E1_only", "image": stem,
            "image_size": [W, H],
            "n_views": len(views),
            "n_rescued": sum(1 for v in views if v["rescued"]),
            "views": views,
            "labels": [ser_serial(s) for s in at["labels"]],
            "prefixes": [ser_serial(s) for s in at["prefixes"]],
            "links": [{"bbox": lk["bbox"], "reason": lk.get("reason", ""),
                       "text": lk.get("text", "")} for lk in at["links"]],
            "scales": scales, "others": others,
            "serial_set": at["rec"].get("serial_set", {}),
            "absorbed_events": at.get("absorbed_events", []),
            "rescued_views": at.get("rescued_views", []),
            "vl_review": at.get("vl_review", []),
            "alarms_e15": at.get("alarms_e15", []),
            "vl": {"enabled": self.vl.enabled,
                   "calls": self.vl.n_calls - vl0[0],
                   "success": self.vl.n_success - vl0[1],
                   "failed": self.vl.failed,
                   "records": self.vl.records[vl0[2]:]},
            "latency_s": round(time.time() - t0, 2),
        }
        with open(os.path.join(out_dir, f"{stem}_e1.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return {
            "ok": True, "stage": "E1_only", "image": stem,
            "image_size": [W, H],
            "n_views": len(views),
            "n_rescued": sum(1 for v in views if v["rescued"]),
            "n_vl_review": len(data["vl_review"]),
            "n_vl_rescued": sum(1 for c in data["vl_review"]
                                if c.get("action") == "rescued_view"),
            "n_alarms_e15": len(data["alarms_e15"]),
            "n_labels": len(data["labels"]),
            "n_prefixes": len(data["prefixes"]),
            "n_links": len(data["links"]),
            "n_scales": len(scales),
            "n_others": len(others),
            "n_absorbed": len(data["absorbed_events"]),
            "e1_json": os.path.join(out_dir, f"{stem}_e1.json"),
            # 兼容既有 CLI 汇总打印 / batch_summary（分组类字段为空；
            # alarms 透出 E1.5 报警供 CLI 打印）
            "n_groups": 0, "groups": [], "merge_log": [], "scales": [],
            "alarms": at.get("alarms_e15", []),
            "vl": {"enabled": self.vl.enabled,
                   "calls": self.vl.n_calls - vl0[0],
                   "success": self.vl.n_success - vl0[1],
                   "failed": self.vl.failed},
            "latency_s": data["latency_s"],
        }

    # ------------------------------------------------------------------
    # E2-only 分阶段评估（在 E1 build_atoms 基础上单独评估 bind_labels）
    # ------------------------------------------------------------------
    def load_atoms_from_e1(self, stem, e1_root="out_e1",
                           src_dir="test_imgs"):
        """从既有 E1 产物 <e1_root>/<stem>/<stem>_e1.json 重建原子 dict。

        E2 单独评估迭代专用：bind_labels 只依赖 views/labels 的 bbox 与
        序号读值，E1 JSON 已完整覆盖（views 含 R1 救援与 E1.5 VL 回捞的
        最终视图清单），因此 E2 可在免 OCR / 免 VL 的情况下与 out_e1 基线
        完全一致地复现——调参迭代秒级完成。掩膜/轮廓不在 E1 JSON 中，置
        None（E2 不使用）；另从源图重算二值墨迹图（仅 OTSU 阈值，不触
        OCR/分割），供 R3c 空白角纠正的列向墨迹检查——源图缺失时置 None，
        E2 自动退化为纯 bbox 判定。
        """
        jp = os.path.join(e1_root, stem, f"{stem}_e1.json")
        with open(jp, encoding="utf-8") as fh:
            d = json.load(fh)
        # 源图 + 二值墨迹（免 OCR）：R3c 空白角纠正依赖
        bgr = binary = None
        src = None
        for ext in (".jpg", ".jpeg", ".png"):
            p = os.path.join(src_dir, stem + ext)
            if os.path.exists(p):
                src = p
                break
        if src is not None:
            bgr, _up = load_image(src)
        if bgr is not None:
            import cv2 as _cv2
            gray = _cv2.cvtColor(bgr, _cv2.COLOR_BGR2GRAY)
            _thr, binary = _cv2.threshold(
                gray, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
            binary = binary > 0
        views = []
        for v in d.get("views", []):
            views.append({
                "id": v["id"], "bbox": list(v["bbox"]),
                "area": v.get("area", 0.0),
                "contour": None, "mask": None,
                "label_nos": [], "label_ranks": [], "label_boxes": [],
                "rescued": bool(v.get("rescued")),
                "rescued_vl": bool(v.get("rescued_vl")),
                # E1 裁片透传（白底掩膜裁片，展示端画廊直接复用）
                "crop_box": v.get("crop_box"),
                "crop_base64": v.get("crop_base64"),
            })

        def ser2label(s):
            lb = {"bbox": list(s["bbox"]), "text": s.get("text", ""),
                  "no": s.get("no", ""), "conf": s.get("conf"),
                  "rotated": bool(s.get("rotated")),
                  "scale_prefix": bool(s.get("scale_prefix"))}
            if s.get("rescued"):
                lb["rescued"] = True
            if s.get("_vl_rescued"):
                lb["_vl_rescued"] = True
            return lb

        links = [dict(lk) for lk in d.get("links", [])]
        # 连接符恢复（R5，from-e1 复现模式）：存量 out_e1 由旧版 E1 规则生
        # 成——"视图内部装饰短线"过滤为纯 bbox 级，会把落在大视图 bbox 空白
        # 区的断裂符一并误删（002 的 V5↔V6 '一'@554、V8↔V9 '-'@511：均落
        # 在 V0 大框内）。此处按现行规则（墨迹级，binary 已为 R3c 加载）对
        # 存储的 others 重跑一次连接符收集，与既有 links 按 bbox 去重合并，
        # 免重跑 OCR 即与现行 E1 行为对齐。
        known = {tuple(lk["bbox"]) for lk in links}
        for o in d.get("others", []):
            ob, reason, txt = o["bbox"], o["reason"], (o.get("text") or "").strip()
            w_ = ob[2] - ob[0]
            h_ = ob[3] - ob[1]
            thin = (h_ >= 2.2 * max(w_, 1)) or (w_ >= 2.2 * max(h_, 1))
            cont = [v for v in views if v["bbox"][0] <= ob[0]
                    and ob[2] <= v["bbox"][2] and v["bbox"][1] <= ob[1]
                    and ob[3] <= v["bbox"][3]]
            if cont and ink_density(binary, ob, pad=12) >= 0.10:
                continue                  # 成片墨迹场内的斑点/装饰短线（R5）
            if tuple(ob) in known:
                continue
            if reason == "connector" or (reason in ("text", "fig_zone")
                                         and txt in DASH_LIKE) \
                    or (reason in ("text", "unreadable", "sliver") and thin
                        and max(w_, h_) <= 60):
                links.append({"bbox": list(ob), "reason": reason,
                              "text": txt})

        return {
            "bgr": bgr, "binary": binary,
            "image_size": (list(bgr.shape[1::-1]) if bgr is not None
                           else list(d.get("image_size") or [None, None])),
            "rec": {"serial_set": d.get("serial_set", {}),
                    "from_e1_json": True},
            "views": views,
            "labels": [ser2label(s) for s in d.get("labels", [])],
            "prefixes": [ser2label(s) for s in d.get("prefixes", [])],
            "links": links,
            "scales": [dict(s) for s in d.get("scales", [])],
            "others": [dict(o) for o in d.get("others", [])],
            "absorbed_fragments": {},
            "absorbed_events": d.get("absorbed_events", []),
            "rescued_views": d.get("rescued_views", []),
            "vl_review": d.get("vl_review", []),
            "alarms_e15": d.get("alarms_e15", []),
            "e1_source": jp,
        }

    def _e2_result(self, stem, at, t0, vl0=None):
        """E2-only 产物落盘 <stem>_e2.json 并返回轻量摘要。

        内容 = E1 原子清单（视图带 E1 掩膜裁片）+ E2 绑定留痕（逐 label
        候选清单/归属/未绑定原因，逐视图挂号结果）+ 评估指标 metrics，
        供独立可视化脚本 archea_show_e2.py 展示与逐图人工复核。
        vl0：live 模式（--e2-only）传入 VL 调用计数基线以统计增量；
        from-e1 复现模式不传（全程无 VL 调用）。
        """
        import base64
        bgr = at.get("bgr")
        e2 = at.get("e2") or {"labels": [], "metrics": {}}
        if bgr is not None:
            H, W = bgr.shape[:2]
        else:
            W, H = at.get("image_size") or (None, None)

        def crop_b64(mask):
            """掩膜 -> (紧致bbox, 白底掩膜裁片 PNG base64)；空掩膜返回空。"""
            if bgr is None or mask is None or not mask.any():
                return None, None
            box, sub = paste_region(mask)
            crop = np.full((sub.shape[0], sub.shape[1], 3), 255, np.uint8)
            crop[sub] = bgr[box[1]:box[3], box[0]:box[2]][sub]
            _ok, buf = cv2.imencode(".png", crop)
            return box, base64.b64encode(buf.tobytes()).decode("ascii")

        views_out = []
        for v in at["views"]:
            if v.get("crop_base64") is not None:      # from-e1：沿用 E1 产物裁片
                cbox, cb64 = v.get("crop_box"), v.get("crop_base64")
            else:
                cbox, cb64 = crop_b64(v.get("mask"))
            views_out.append({
                "id": v["id"], "bbox": v["bbox"], "area": v["area"],
                "rescued": bool(v.get("rescued")),
                "rescued_vl": bool(v.get("rescued_vl")),
                "label_nos": list(v["label_nos"]),
                "label_inherited": {k: dict(val) for k, val
                                    in (v.get("label_inherited") or {}).items()},
                "label_boxes": [list(b) for b in v.get("label_boxes", [])],
                "label_idx": list(v.get("label_idx", [])),
                "crop_box": cbox, "crop_base64": cb64})

        trace_by_idx = {t["idx"]: t for t in e2.get("labels", [])}
        labels_out = []
        for li, lb in enumerate(at["labels"]):
            t = trace_by_idx.get(li, {})
            labels_out.append({
                "idx": li, "bbox": list(lb["bbox"]),
                "text": lb.get("text", ""), "no": lb.get("no", ""),
                "conf": lb.get("conf"),
                "rescued": bool(lb.get("rescued")),
                "_vl_rescued": bool(lb.get("_vl_rescued")),
                "status": t.get("status", "unknown"),
                "stiff": t.get("stiff", False),
                "attach": t.get("attach"),
                "rank": t.get("rank"), "rel": t.get("rel"),
                "gap": t.get("gap"),
                "conflict_view": t.get("conflict_view"),
                "candidates": t.get("candidates", [])})

        m = dict(e2.get("metrics", {}))
        out_dir = os.path.join(self.out_root, stem)
        os.makedirs(out_dir, exist_ok=True)
        data = {
            "ok": True, "stage": "E2_only", "image": stem,
            "image_size": [W, H],
            "e1_source": at.get("e1_source"),
            "atoms": {
                "n_views": len(views_out),
                "n_rescued": sum(1 for v in views_out if v["rescued"]),
                "n_labels": len(labels_out),
                "n_prefixes": len(at["prefixes"]),
                "n_links": len(at["links"]),
                "n_scales": len(at["scales"]),
                "n_others": len(at["others"]),
                "n_absorbed": len(at.get("absorbed_events", [])),
            },
            "views": views_out,
            "labels": labels_out,
            "prefixes": [{"bbox": s["bbox"], "text": s.get("text", ""),
                          "no": s.get("no", ""), "conf": s.get("conf")}
                         for s in at["prefixes"]],
            "scales": [{"kind": s.get("kind"), "bbox": s["bbox"],
                        "bar_bbox": s.get("bar_bbox"),
                        "text": s.get("text", ""), "value": s.get("value"),
                        "unit": s.get("unit")} for s in at["scales"]],
            "metrics": m,
            "params": e2.get("params", {}),
            "links": e2.get("links", []),
            "serial_set": (at.get("rec") or {}).get("serial_set", {}),
            "alarms_e15": at.get("alarms_e15", []),
            "vl": ({"enabled": self.vl.enabled,
                    "calls": self.vl.n_calls - vl0[0],
                    "success": self.vl.n_success - vl0[1],
                    "failed": self.vl.failed}
                   if vl0 is not None else
                   {"enabled": False, "calls": 0, "success": 0,
                    "note": "from-e1 复现模式：E1 产物直接复用，无 VL 调用"}),
            "latency_s": round(time.time() - t0, 2),
        }
        p = os.path.join(out_dir, f"{stem}_e2.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        summary = {
            "ok": True, "stage": "E2_only", "image": stem,
            "image_size": [W, H],
            "n_views": len(views_out),
            "n_rescued": sum(1 for v in views_out if v["rescued"]),
            "n_labels": len(labels_out),
            "n_valid": m.get("n_valid", 0),
            "n_assigned": m.get("n_assigned", 0),
            "assign_rate": m.get("assign_rate"),
            "n_no_candidate": m.get("n_no_candidate", 0),
            "n_conflict": m.get("n_conflict_dropped", 0),
            "n_inner_yielded": m.get("n_inner_yielded", 0),
            "n_uniqueness_dropped": m.get("n_uniqueness_dropped", 0),
            "n_above_rejected": m.get("n_above_rejected", 0),
            "n_views_labeled": m.get("n_views_labeled", 0),
            "n_views_unlabeled": m.get("n_views_unlabeled", 0),
            "n_inherited": m.get("n_inherited", 0),
            "n_inherited_views": m.get("n_inherited_views", 0),
            "n_links": len(at.get("links", [])),
            "n_views_unlabeled_after": m.get("n_views_unlabeled_after",
                                             m.get("n_views_unlabeled", 0)),
            "set_nums_unbound": m.get("set_nums_unbound", []),
            "bound_nos_not_in_set": m.get("bound_nos_not_in_set", []),
            "e2_json": p,
            # 兼容既有 CLI 汇总打印 / batch_summary（分组类字段为空；
            # alarms 透出 E1.5 报警供 CLI 打印）
            "n_groups": 0, "groups": [], "merge_log": [], "scales": [],
            "alarms": at.get("alarms_e15", []),
            "vl": ({"enabled": self.vl.enabled,
                    "calls": self.vl.n_calls - vl0[0],
                    "success": self.vl.n_success - vl0[1],
                    "failed": self.vl.failed}
                   if vl0 is not None else
                   {"enabled": False, "calls": 0, "success": 0,
                    "failed": None}),
            "latency_s": data["latency_s"],
        }
        return summary

    def extract_e2_from_e1(self, stem, e1_root="out_e1", src_dir="test_imgs"):
        """E2 单独评估（from-e1 复现模式）：读取既有 E1 产物 -> bind_labels。

        免 OCR / 免 VL / 免分割，与 out_e1 基线完全一致；调参迭代秒级。
        源图仅用于重算二值墨迹（R3c 空白角纠正）与 E2 JSON 视图裁片。
        返回 _e2_result 摘要（e2_json 路径 + 指标）。
        """
        t0 = time.time()
        at = self.load_atoms_from_e1(stem, e1_root, src_dir)
        self.bind_labels(at)
        return self._e2_result(stem, at, t0)

    # ------------------------------------------------------------------
    # E3 单独评估（from-e2 复现模式）：读取既有 E2 产物 -> group_views
    # ------------------------------------------------------------------
    def load_atoms_from_e2(self, stem, e2_root="out_e2", src_dir="test_imgs"):
        """从既有 E2 产物 <e2_root>/<stem>/<stem>_e2.json 重建原子 dict。

        E3 单独评估迭代专用：group_views 只依赖 views 的 bbox / label_nos /
        label_ranks（G1 只认 rank<3 外部证据）与 links 的 bbox（G2 端点解析，
        需二值墨迹图做最近墨迹消歧），E2 JSON 已完整覆盖。与 out_e2 基线
        完全一致地复现 E3——免 OCR / 免分割 / 免 E1.5，调参迭代秒级。

        label_ranks 重建：E2 JSON 的 views 未直接存 rank，但 label_idx 与
        labels 一一对应（labels[idx]["rank"] 即该直接绑定号的证据方位）；
        连接符继承号（E2.1）按约定记 rank=4（不作 G1 证据），按
        len(label_nos) - len(label_idx) 补齐——与 bind_labels 步骤 4/5 的
        追加顺序（先直接后继承）严格一致。

        bgr/binary 从源图重算（VL 裁片仲裁 + G2 墨迹解析）；源图缺失时置
        None（VL 仲裁自动放弃，G2 退化为纯 bbox 解析）。掩膜不在 E2 JSON
        中，置 None（E3 不使用）；视图裁片沿用 E2 产物透传（展示端画廊
        直接复用，免重算）。
        """
        jp = os.path.join(e2_root, stem, f"{stem}_e2.json")
        with open(jp, encoding="utf-8") as fh:
            d = json.load(fh)
        # 源图 + 二值墨迹（免 OCR）：G2 端点最近墨迹解析 / VL 裁片依赖
        bgr = binary = None
        src = None
        for ext in (".jpg", ".jpeg", ".png"):
            p = os.path.join(src_dir, stem + ext)
            if os.path.exists(p):
                src = p
                break
        if src is not None:
            bgr, _up = load_image(src)
        if bgr is not None:
            import cv2 as _cv2
            gray = _cv2.cvtColor(bgr, _cv2.COLOR_BGR2GRAY)
            _thr, binary = _cv2.threshold(
                gray, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
            binary = binary > 0
        labels = d.get("labels", [])
        views = []
        for v in d.get("views", []):
            # label_ranks 重建：直接绑定号取 labels[label_idx]["rank"]；
            # 继承号（E2.1）固定 rank4（不作 G1 同号证据，与 live 一致）
            ranks = [labels[i]["rank"] for i in v.get("label_idx", [])
                     if i < len(labels) and labels[i].get("rank") is not None]
            n_inh = max(0, len(v.get("label_nos", [])) - len(ranks))
            views.append({
                "id": v["id"], "bbox": list(v["bbox"]),
                "area": v.get("area", 0.0),
                "contour": None, "mask": None,
                "label_nos": list(v.get("label_nos", [])),
                "label_ranks": ranks + [4] * n_inh,
                "label_boxes": [list(b) for b in v.get("label_boxes", [])],
                "label_idx": list(v.get("label_idx", [])),
                "label_inherited": {k: dict(val) for k, val
                                    in (v.get("label_inherited") or {}).items()},
                "rescued": bool(v.get("rescued")),
                "rescued_vl": bool(v.get("rescued_vl")),
                # E2 裁片透传（白底掩膜裁片，展示端画廊直接复用）
                "crop_box": v.get("crop_box"),
                "crop_base64": v.get("crop_base64"),
            })
        # 视图墨迹掩膜重建（源图可用时）：G2 包含型候选的墨迹校验、E5 组装
        # 防串染剔除都依赖 mask，重放路径不再置 None
        self._rebuild_view_masks(views, binary)
        return {
            "bgr": bgr, "binary": binary,
            "image_size": (list(bgr.shape[1::-1]) if bgr is not None
                           else list(d.get("image_size") or [None, None])),
            "rec": {"serial_set": d.get("serial_set", {}),
                    "from_e2_json": True},
            "views": views,
            # E2 标签轻量重建（供 overlay / JSON 上下文；不重跑绑定逻辑）
            "labels": [{"bbox": list(lb["bbox"]), "text": lb.get("text", ""),
                        "no": lb.get("no", ""), "conf": lb.get("conf"),
                        "_attach": lb.get("attach"),
                        "_e2_status": lb.get("status", "unknown")}
                       for lb in labels],
            "prefixes": [], "links": [dict(lk) for lk in d.get("links", [])],
            "scales": [], "others": [],
            "absorbed_fragments": {},
            "absorbed_events": [],
            "rescued_views": [],
            "vl_review": [],
            "alarms_e15": d.get("alarms_e15", []),
            "e2_stats": d.get("metrics", {}),
            "e2_source": jp,
        }

    @staticmethod
    def _rebuild_view_masks(views, binary):
        """from-e2 重放掩膜重建：按连通分量归属，而非 bbox 内原始二值。

        bbox 原始二值会把未分割的游离墨迹一并算进罩住它的视图（002 无钩
        世界实证：断钩墨迹落在号4大框 bbox 内，ink_mask 口径下 V0 掩膜
        "自有"墨迹距端点仅 4px，包含型候选盲采否决失效）。连通分量口径：
        分量质心落在哪个视图 bbox 内就归谁（嵌套时小 bbox 后写覆盖大
        bbox）；无归属分量（游离碎墨）不进任何视图掩膜——与 E1 轮廓填充
        掩膜的自有墨迹口径一致。"""
        if binary is None or not views:
            return
        import cv2 as _cv2
        n, lab, _st, cents = _cv2.connectedComponentsWithStats(
            binary.astype(np.uint8), connectivity=8)
        if n <= 1:
            return
        cx, cy = cents[:, 0], cents[:, 1]
        lut = np.zeros(n, dtype=np.int32)     # 分量id -> 视图序号+1
        for vi in sorted(range(len(views)),
                         key=lambda i: -(views[i]["bbox"][2]
                                         - views[i]["bbox"][0])
                         * (views[i]["bbox"][3] - views[i]["bbox"][1])):
            x0, y0, x1, y1 = views[vi]["bbox"]
            sel = (cx >= x0) & (cx <= x1) & (cy >= y0) & (cy <= y1)
            sel[0] = False                    # 背景分量不归属
            lut[sel] = vi + 1
        view_of_pix = lut[lab]
        for vi, v in enumerate(views):
            vm = view_of_pix == (vi + 1)
            if vm.any():
                v["mask"] = vm

    def extract_e3_from_e2(self, stem, e2_root="out_e2", src_dir="test_imgs"):
        """E3 单独评估（from-e2 复现模式）：读取既有 E2 产物 -> group_views。

        免 OCR / 免分割 / 免 E1.5，视图序号绑定与 out_e2 基线完全一致；
        调参迭代秒级。VL 默认可用（G3/G4 歧义仲裁真实需要，--no-vl 关闭后
        纯 CV 迭代、VL 触点仅在 stats 留痕）。源图用于重算二值墨迹（G2 端
        点解析）与 VL 裁片。返回 _e3_result 摘要（e3_json 路径 + 指标）。
        """
        t0 = time.time()
        at = self.load_atoms_from_e2(stem, e2_root, src_dir)
        groups, merge_log = self.group_views(at)
        return self._e3_result(stem, at, groups, merge_log, t0)

    def _merge_log_alarms(self, merge_log):
        """merge_log -> 报警事件（e3-only 与全流程共用）：S1 多物体报警、
        S2/G4 守卫 hold、VL 歧义放弃孤立/吸附。"""
        alarms = []
        for mrec in merge_log:
            if mrec["rule"] == "G0_multi_object_alarm":
                alarms.append({"code": "no_serial_multi_object",
                               "msg": f"⚠ 报警：{mrec['note']}（规范：无序号"
                                      f"多物体图必须人工复核，禁止强制配对）",
                               "note": mrec["note"]})
            elif mrec["rule"] == "G3_guard_hold":
                alarms.append({"code": "guard_hold",
                               "msg": f"⚠ 报警：无号完整视图{mrec['views']} 几何"
                                      f"吸附被完整视图守卫拦截，保持独立待复核",
                               "note": mrec["note"]})
            elif mrec["rule"] == "G4_guard_hold":
                alarms.append({"code": "guard_hold",
                               "msg": f"⚠ 报警：带号视图{mrec['views']} 吸附被"
                                      f"完整视图守卫拦截，未并入待复核",
                               "note": mrec["note"]})
            elif mrec["rule"] == "G3_vl_abandon":
                alarms.append({"code": "orphan_ambiguous",
                               "msg": f"⚠ 报警：孤立视图{mrec['views']} 归属歧义，"
                                      f"VL 裁决未通过，保持独立待复核",
                               "note": mrec["note"]})
            elif mrec["rule"] == "G4_vl_abandon":
                alarms.append({"code": "absorb_ambiguous",
                               "msg": f"⚠ 报警：带号视图{mrec['views']} 吸附歧义，"
                                      f"VL 裁决未通过，保持独立待复核",
                               "note": mrec["note"]})
        return alarms

    def _consistency_checks(self, at, groups):
        """组-序号一致性核查（e3-only 与全流程共用的单一实现，002 教训：
        全流程此前无任何组 vs 序号检查点，['4','6'] 混号组与 7 号 6 组
        缺口静默直达出图）：
          - group_multi_no：组内多个直接号（rank<3，异器物误并最直接信号）；
          - serial_group_mismatch：组携带号去重集合（direct+inside+inherited）
            元素数 != 有号组数（同号跨组/拆组）。
        serial_set 只作观测不参与判定（S3 口径）。返回 (alarms, metrics)。"""
        def _numkey(x):
            return int(x) if str(x).isdigit() else 99

        multi_no, any_no_groups, nos_union = [], 0, set()
        for gi, g in enumerate(groups):
            dnos, anos = set(), set()
            for i in g:
                v = at["views"][i]
                for no, rk in zip(v["label_nos"], v.get("label_ranks", [])):
                    if not no:
                        continue
                    anos.add(no)
                    if rk < 3:
                        dnos.add(no)
            nos_union |= anos
            if anos:
                any_no_groups += 1
            if len(dnos) > 1:
                multi_no.append({
                    "group_id": gi, "view_ids": list(g),
                    "nos": sorted(dnos, key=_numkey)})
        alarms = [{"code": "group_multi_no",
                   "msg": f"⚠ 报警：组{m['group_id']} 含多个序号{m['nos']}"
                          f"（视图{m['view_ids']}），疑似异器物误并，请复核",
                   "view_ids": m["view_ids"], "nos": m["nos"]}
                  for m in multi_no]
        mismatch = any_no_groups != len(nos_union)
        if mismatch:
            alarms.append({
                "code": "serial_group_mismatch",
                "msg": f"⚠ 报警：有号组{any_no_groups} != 组携带号去重集合"
                       f"{len(nos_union)}（{sorted(nos_union, key=_numkey)}），"
                       f"号-组不对应（同号跨组/拆组），请复核"})
        metrics = {"nos_union": sorted(nos_union, key=_numkey),
                   "n_nos_union": len(nos_union),
                   "n_groups_any_no": any_no_groups,
                   "nos_groups_mismatch": mismatch,
                   "n_multi_no_groups": len(multi_no),
                   "multi_no_groups": multi_no}
        return alarms, metrics

    def _e3_result(self, stem, at, groups, merge_log, t0):
        """E3-only 产物落盘 <stem>_e3.json 并返回轻量摘要。

        内容 = 输入原子清单（视图带 E2 绑定号与裁片）+ 分组结果（逐组成员/
        组号/合并证据链）+ 逐规则合并日志 + 评估指标（组数/组规模分布/
        带号组覆盖/孤立无号组/多号可疑组/逐规则合并计数/VL 触点），
        供独立可视化脚本 archea_show_e3.py 展示与逐图人工复核。
        """
        import base64
        bgr = at.get("bgr")
        if bgr is not None:
            H, W = bgr.shape[:2]
        else:
            W, H = at.get("image_size") or (None, None)
        views = at["views"]

        # 逐组证据链：merge_log 中双端均落在同组的条目即该组的合并依据
        evidence = {}                     # view_id -> [merge_entry,...]
        for mrec in merge_log:
            vs = [i for i in mrec.get("views", []) if i is not None]
            for i in vs:
                evidence.setdefault(i, []).append(mrec)

        def _numkey(s):
            return (0, int(s)) if str(s).isdigit() else (1, s)

        groups_out = []
        for gi, g in enumerate(groups):
            # 组内序号按证据等级分三档（与 G1 只认 rank<3 的口径一致）：
            #   direct    rank<3  外部绑定号（分组/命名依据）
            #   inside    rank==3 视图内部兜底号（不作 G1 证据，拓片幻影高发）
            #   inherited rank==4 E2.1 连接符继承号（归属显式化）
            buckets = {"direct": [], "inside": [], "inherited": []}
            for i in g:
                for no, rk in zip(views[i]["label_nos"],
                                  views[i]["label_ranks"]):
                    key = ("direct" if rk < 3
                           else "inside" if rk == 3 else "inherited")
                    if no not in buckets[key]:
                        buckets[key].append(no)
            for v_ in buckets.values():
                v_.sort(key=_numkey)
            ev, seen = [], set()
            for i in g:                   # 组内成员的合并依据去重汇总
                for mrec in evidence.get(i, []):
                    key = (mrec["rule"], tuple(mrec.get("views", [])),
                           mrec.get("note", ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    ev.append({"rule": mrec["rule"],
                               "views": list(mrec.get("views", [])),
                               "note": mrec.get("note", "")})
            boxes = [views[i]["bbox"] for i in g]
            groups_out.append({
                "group_id": gi, "view_ids": list(g),
                "n_views": len(g),
                "union_bbox": union_box(boxes),
                "label_nos": buckets["direct"],          # 与全流程命名口径一致
                "label_nos_inside": buckets["inside"],
                "label_nos_inherited": buckets["inherited"],
                "evidence": ev})

        # S5 E2 丢弃/落选号 -> 组级"待复核号"提示：只标注、不参与 G1/G4
        # 判定（rank5 语义）。挂在几何紧邻（<=label_gap）的无直接号组上；
        # 每个丢弃号只归最近的一个候选组，画廊橙色虚线框标出供人工复核
        # （image392/436 印于视图下方的 '1'、image962 被丢弃的 '7' 等）。
        _pend_status = ("conflict_dropped", "uniqueness_dropped",
                        "no_candidate", "invalid")

        def _label_status_e3(lb):
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

        open_groups = [g for g in groups_out if not g["label_nos"]]
        pending_total = 0
        for li, lb in enumerate(at["labels"]):
            if _label_status_e3(lb) not in _pend_status:
                continue
            bb = lb["bbox"]
            if max(bb[2] - bb[0], bb[3] - bb[1]) < 8:
                continue                               # 碎屑噪声
            best_g, best_d, best_v = None, None, None
            for g in open_groups:
                for vid in g["view_ids"]:
                    vb = views[vid]["bbox"]
                    gx = max(0, max(vb[0], bb[0]) - min(vb[2], bb[2]))
                    gy = max(0, max(vb[1], bb[1]) - min(vb[3], bb[3]))
                    d_ = max(gx, gy)
                    if best_d is None or d_ < best_d:
                        best_g, best_d, best_v = g, d_, vid
            if best_g is not None and best_d <= self.p_label_gap:
                best_g.setdefault("pending_nos", []).append({
                    "no": lb.get("no", ""), "conf": lb.get("conf"),
                    "e2_status": _label_status_e3(lb), "label_idx": li,
                    "gap": int(best_d), "view_id": best_v,
                    "label_bbox": list(bb)})
                pending_total += 1
        for g in groups_out:
            g.get("pending_nos", []).sort(
                key=lambda c: (c["gap"], c["label_idx"]))

        # S3 度量口径重建：序号核对基准改为"组内实际携带的去重号集合"
        # （direct+inside+inherited 并集），serial_set 只保留给 E2.5 补救与
        # 漏检观测——修复 serial_set 幻影/漏读造成的 N>M 假阳性
        # （image160/236/238/261 四图皆因 serial_set 漏 '1' 误标）。
        nos_union = sorted({no for g in groups_out
                            for no in (g["label_nos"] + g["label_nos_inside"]
                                       + g["label_nos_inherited"])},
                           key=_numkey)

        # 逐视图清单（带 E2 绑定号 + E1 裁片透传，供画廊与后续复现）
        views_out = []
        for v in views:
            if v.get("crop_base64") is not None:      # from-e2：沿用 E2 产物裁片
                cbox, cb64 = v.get("crop_box"), v.get("crop_base64")
            else:
                cbox, cb64 = None, None
                if bgr is not None and v.get("mask") is not None:
                    box_, sub = paste_region(v["mask"])
                    crop = np.full((sub.shape[0], sub.shape[1], 3), 255, np.uint8)
                    crop[sub] = bgr[box_[1]:box_[3], box_[0]:box_[2]][sub]
                    _ok, buf = cv2.imencode(".png", crop)
                    cbox, cb64 = box_, base64.b64encode(buf.tobytes()).decode(
                        "ascii")
            views_out.append({
                "id": v["id"], "bbox": v["bbox"], "area": v["area"],
                "rescued": bool(v.get("rescued")),
                "rescued_vl": bool(v.get("rescued_vl")),
                "label_nos": list(v["label_nos"]),
                "label_ranks": list(v.get("label_ranks", [])),
                "label_inherited": {k: dict(val) for k, val
                                    in (v.get("label_inherited") or {}).items()},
                "label_boxes": [list(b) for b in v.get("label_boxes", [])],
                "label_idx": list(v.get("label_idx", [])),
                "crop_box": cbox, "crop_base64": cb64})

        # 评估指标
        size_hist = {}
        for g in groups:
            k = str(len(g)) if len(g) < 3 else "3+"
            size_hist[k] = size_hist.get(k, 0) + 1
        rule_counts = dict(sorted(
            ((k, v) for k, v in (at.get("e3_stats") or {}).get(
                "merges", {}).items()),
            key=lambda kv: (-kv[1], kv[0])))
        multi_no = [g for g in groups_out if len(g["label_nos"]) > 1]
        orphans = [g for g in groups_out
                   if len(g["view_ids"]) == 1 and not g["label_nos"]]
        ruleB = [g for g in groups_out
                 if any(e["rule"] == "G0_no_serial_ruleB" for e in g["evidence"])]
        n_vl_abandon = sum(1 for mrec in merge_log
                           if mrec["rule"].endswith("_vl_abandon"))
        n_views_labeled = sum(1 for v in views if v["label_nos"])
        _st = at.get("e3_stats") or {}
        n_groups_any_no = sum(1 for g in groups_out
                              if g["label_nos"] or g["label_nos_inside"]
                              or g["label_nos_inherited"])
        metrics = {
            "n_views": len(views),
            "n_views_labeled": n_views_labeled,          # 含继承号（rank4）
            "n_views_unlabeled": len(views) - n_views_labeled,
            "n_groups": len(groups_out),
            "group_size_hist": size_hist,
            "n_groups_labeled": sum(1 for g in groups_out
                                    if g["label_nos"]),
            "n_groups_unlabeled": sum(1 for g in groups_out
                                      if not g["label_nos"]),
            # 有号口径（含内部号/继承号任一）：docx 每序号一件器物的核对基准
            "n_groups_any_no": n_groups_any_no,
            # S3 口径：组携带号去重集合（核对基准），与有号组数不等即"号-组
            # 不对应"（同号跨组/拆组），serial_set 不再参与核对
            "nos_union": nos_union,
            "n_nos_union": len(nos_union),
            "nos_groups_mismatch": n_groups_any_no != len(nos_union),
            "n_multi_no_groups": len(multi_no),          # 可疑混组（组内多个直接号）
            "multi_no_groups": [{"group_id": g["group_id"],
                                 "view_ids": g["view_ids"],
                                 "nos": g["label_nos"]} for g in multi_no],
            "n_orphan_groups": len(orphans),             # 孤立无号单例（G3/G4 未吸附）
            "orphan_groups": [{"group_id": g["group_id"],
                               "view_id": g["view_ids"][0],
                               "bbox": views[g["view_ids"][0]]["bbox"]}
                              for g in orphans],
            "n_ruleB_merges": len(ruleB),                # 全图无号规则B合并的组
            "rule_counts": rule_counts,                  # 逐规则合并次数
            "n_merge_events": sum(rule_counts.values()),
            "n_vl_abandon": n_vl_abandon,
            "vl_touchpoints": _st.get("vl_touchpoints", 0),
            "g3_touch_shallow_vl": _st.get("g3_touch_shallow_vl", 0),
            "g3_ambiguous": _st.get("g3_ambiguous", 0),
            "g4_ambiguous": _st.get("g4_ambiguous", 0),
            "g4_absorb": _st.get("g4_absorb", 0),
            # S1/S2/S4 留痕
            "s1_gate_fired": bool(_st.get("s1_gate_fired")),
            "s1_gate_components": _st.get("s1_gate_components", 0),
            "s2_guard_touchpoints": _st.get("s2_guard_touchpoints", 0),
            "s2_guard_vl_merged": _st.get("s2_guard_vl_merged", 0),
            "s2_guard_holds": _st.get("s2_guard_holds", 0),
            "s4_ext_attempt": _st.get("s4_ext_attempt", 0),
            "s4_ext_merged": _st.get("s4_ext_merged", 0),
            "n_pending_nos": pending_total,
        }

        # 报警口径与全流程一致：VL 歧义放弃 -> 待复核；须在 e3.json 落盘前
        # 装配完成（alarms 持久化进 e3.json，供 show 与后续工具直接消费）
        alarms = self._merge_log_alarms(merge_log)
        # 组-序号一致性报警：与全流程共用单一实现（组内多号 group_multi_no +
        # 号数≠组数 serial_group_mismatch），消除两种模式的检查口径漂移
        cons_alarms, _ = self._consistency_checks(at, groups)
        alarms.extend(cons_alarms)

        out_dir = os.path.join(self.out_root, stem)
        os.makedirs(out_dir, exist_ok=True)
        data = {
            "ok": True, "stage": "E3_only", "image": stem,
            "image_size": [W, H],
            "e2_source": at.get("e2_source"),
            "e1_source": None,
            "atoms": {
                "n_views": len(views_out),
                "n_rescued": sum(1 for v in views_out if v["rescued"]),
                "n_labels": len(at["labels"]),
                "n_prefixes": len(at["prefixes"]),
                "n_links": len(at["links"]),
                "n_scales": len(at["scales"]),
                "n_others": len(at["others"]),
            },
            "views": views_out,
            "labels": [{"idx": li, "bbox": list(lb["bbox"]),
                        "text": lb.get("text", ""), "no": lb.get("no", ""),
                        "conf": lb.get("conf"), "attach": lb.get("_attach"),
                        "e2_status": lb.get("_e2_status", "unknown")}
                       for li, lb in enumerate(at["labels"])],
            "links": [{"bbox": lk.get("bbox"), "text": lk.get("text"),
                       "reason": lk.get("reason"), "cls": lk.get("cls"),
                       "ends": lk.get("ends")}
                      for lk in at["links"]],
            "groups": groups_out,
            "merge_log": merge_log,
            "metrics": metrics,
            "alarms": alarms,
            "params": {
                "link_gap": self.p_link_gap,
                "stack_gap_max": self.p_stack_gap,
                "row_gap_max": self.p_row_gap,
                "row_auto_max": self.p_row_auto_max,
                "stack_xov": self.p_stack_xov,
                "row_yov": self.p_row_yov,
                "e3_rescue": self.e3_rescue,
                "g1_evidence": "rank<3 外部绑定号同号必同组",
                "g2": "_resolve_link_ends（端点最近墨迹）+ S4 轴线延伸（单端空时）",
                "g3": "无号组迭代吸附（touch/stack/row；浅相交带号目标须 VL；"
                      "完整视图+丢弃号信号 row/stack 走 S2 守卫）",
                "g4": "带号单例吸附紧邻无号组（gap<=30, xov>=0.5；S2 守卫同适用）",
                "s1": "无外部序号图 G1/G2 连通分量>=2 -> 报警不合并（G3/G4/G0 跳过）",
                "s2": "完整视图(面积>=0.5x中位数)+就近丢弃序号 -> row/stack 降级 VL",
                "s4": "连接符轴线延伸：主轴相交+空端一侧+带内墨迹校验",
                "vl_enabled": self.vl.enabled,
            },
            "serial_set": (at.get("rec") or {}).get("serial_set", {}),
            "alarms_e15": at.get("alarms_e15", []),
            "vl": {"enabled": self.vl.enabled,
                   "calls": self.vl.n_calls,
                   "success": self.vl.n_success,
                   "failed": self.vl.failed},
            "latency_s": round(time.time() - t0, 2),
        }
        p = os.path.join(out_dir, f"{stem}_e3.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        # 分组叠加可视化（复用全流程 overlay；E3 阶段无比例尺绑定为空）
        overlay = None
        if bgr is not None:
            overlay = self.draw_overlay(bgr, at, groups,
                                        [[] for _ in groups])
            ok_, buf = cv2.imencode(".png", overlay)
            buf.tofile(os.path.join(out_dir, f"{stem}_e3_overlay.png"))
        summary = {
            "ok": True, "stage": "E3_only", "image": stem,
            "image_size": [W, H],
            "n_views": len(views_out),
            "n_labels": len(at["labels"]),
            "n_groups": len(groups_out),
            "groups": [{"group_id": g["group_id"], "view_ids": g["view_ids"],
                        "label_nos": g["label_nos"],
                        "label_nos_inside": g["label_nos_inside"],
                        "label_nos_inherited": g["label_nos_inherited"],
                        "output": None, "scales": []} for g in groups_out],
            "merge_log": merge_log,
            "metrics": metrics,
            "group_size_hist": size_hist,
            "rule_counts": rule_counts,
            "n_multi_no_groups": len(multi_no),
            "n_orphan_groups": len(orphans),
            "n_vl_abandon": n_vl_abandon,
            "vl_touchpoints": metrics["vl_touchpoints"],
            "e3_json": p,
            "e3_overlay": (os.path.join(out_dir, f"{stem}_e3_overlay.png")
                           if overlay is not None else None),
            "alarms": alarms,
            "vl": {"enabled": self.vl.enabled,
                   "calls": self.vl.n_calls,
                   "success": self.vl.n_success,
                   "failed": self.vl.failed},
            "latency_s": data["latency_s"],
        }
        return summary

    # ------------------------------------------------------------------
    # 单图主流程
    # ------------------------------------------------------------------
    def extract_image(self, image, stem=None):
        t0 = time.time()
        vl0 = (self.vl.n_calls, self.vl.n_success, len(self.vl.records))
        bgr, _up = load_image(image)
        if bgr is None:
            return {"ok": False, "error": "imread failed"}
        stem = stem or os.path.splitext(os.path.basename(
            image if isinstance(image, (str, os.PathLike)) else "image"))[0]
        at = self.build_atoms(bgr)
        # E1.5 VL 二次判定：候选漏斗 + 三态合并（回捞视图 / 维持 / 报警）
        self.vl_review(at)

        # ==================================================================
        # 分阶段效果评估（E1-only）：只运行到 E1 原子收集 build_atoms。
        # 注意：这是常驻的分阶段评估模式（非临时停用开关）——E1 调参迭代用
        # （配合 --from-e1 可秒级复现 E2），全流程不带 --e1-only 即可。
        # ==================================================================
        if self.e1_only:
            # self.bind_labels(at)                         # E2 序号→视图归属（停用）
            # self.rescue_missing_serials(at)              # E2.5 序号漏检 VL 补救（停用）
            # groups, merge_log = self.group_views(at)     # E3 视图分组（停用）
            # bound, scale_records, alarms = self.bind_scales(at, groups)  # E4 比例尺绑定（停用）
            # E5 compose_group / 命名出图 / overlay / 报警汇总（停用）
            res = self._e1_result(image, stem, at, t0, vl0)
            if self.review_sheet:
                res["vl_review_sheet"] = self.write_vl_review_sheet(at, stem)
            return res

        # ==================================================================
        # 分阶段效果评估（E2-only）：E1 原子收集 + E1.5 VL 复核后只运行
        # E2 序号→视图绑定，产物 <stem>_e2.json 供 archea_show_e2.py 单独
        # 展示评估（常驻分阶段模式，非临时停用开关）；
        # 批量复现迭代用 --from-e1 更快。
        # ==================================================================
        if self.e2_only:
            self.bind_labels(at)                         # E2 序号→视图归属（含 E2.1 连接符继承）
            # self.rescue_missing_serials(at)              # E2.5 VL 补救（E2 评估默认停用）
            # groups, merge_log = self.group_views(at)     # E3 视图分组（停用）
            # bound, scale_records, alarms = self.bind_scales(at, groups)  # E4（停用）
            # E5 compose_group / 命名出图 / overlay / 报警汇总（停用）
            res = self._e2_result(stem, at, t0, vl0)
            if self.review_sheet:
                res["vl_review_sheet"] = self.write_vl_review_sheet(at, stem)
            return res

        # ==================================================================
        # 分阶段效果评估（E3-only）：E1 原子收集 + E1.5 VL 复核 + E2 序号绑定
        # （含 E2.1 连接符继承）后只运行 E3 视图分组，产物 <stem>_e3.json 供
        # archea_show_e3.py 单独展示评估（常驻分阶段模式，非临时停用开关）；
        # 批量复现迭代用 --from-e2 更快。E2.5 rescue 默认开启（与全流程同
        # 口径，--e3-no-rescue 退出；from-e2 重放路径已烘焙回捞、强制跳过）。
        # ==================================================================
        if self.e3_only:
            self.bind_labels(at)                         # E2 序号→视图归属（含 E2.1 连接符继承）
            if self.e3_rescue:
                # E2.5 VL 补救：与全流程口径一致（from-e2 重放的 out_e2 已烘焙
                # 回捞结果，新跑路径跳过会导致两种 E3 输入不同口径）
                self.rescue_missing_serials(at)
            groups, merge_log = self.group_views(at)     # E3 视图分组
            # bound, scale_records, alarms = self.bind_scales(at, groups)  # E4 比例尺绑定（停用）
            # E5 compose_group / 命名出图 / 报警汇总（停用）
            res = self._e3_result(stem, at, groups, merge_log, t0)
            if self.review_sheet:
                res["vl_review_sheet"] = self.write_vl_review_sheet(at, stem)
            return res

        self.bind_labels(at)
        self.rescue_missing_serials(at)
        groups, merge_log = self.group_views(at)
        # 组-序号一致性核查（与 e3-only 共用单一实现；002：['4','6'] 混号组
        # 与 7 号 6 组缺口此前在全流程无检查点，静默直达出图）
        cons_alarms, cons_metrics = self._consistency_checks(at, groups)
        bound, scale_records, alarms = self.bind_scales(at, groups)

        out_dir = os.path.join(self.out_root, stem)
        os.makedirs(out_dir, exist_ok=True)

        # 组序号命名：优先器物序号；无号组 01/02 递增
        used, group_records = set(), []
        auto = 0
        for gi, g in enumerate(groups):
            nos = sorted({no for i in g for no in at["views"][i]["label_nos"]
                          if no}, key=lambda x: int(x) if x.isdigit() else 99)
            seq = nos[0] if nos else None
            if seq is None:
                auto += 1
                seq = f"{auto:02d}"
                while seq in used:
                    auto += 1
                    seq = f"{auto:02d}"
            used.add(seq)
            canvas, grec = self.compose_group(at, g, bound[gi], seq)
            grec["group_id"] = gi
            grec["view_ids"] = list(g)
            grec["label_nos_all"] = nos
            if canvas is not None:
                path = os.path.join(out_dir, f"{stem}_{seq}.png")
                ok, buf = cv2.imencode(".png", canvas)
                buf.tofile(path)
                grec["output"] = path
            else:
                grec["output"] = None
                grec["error"] = grec.get("error", "compose failed")
                alarms.append({"code": "compose_failed", "group": gi,
                               "msg": f"⚠ 报警：器物组{gi} 组装失败"})
            group_records.append(grec)

        # 序号全集口径：并入 'i'/'l' 救援出的序号（261 的 '1' 被 OCR 读成 'i'，
        # rec.serial_set 里缺号会误报 missing）
        _ss = dict(at["rec"]["serial_set"])
        _rescued_nos = {(lb.get("no") or "").strip() for lb in at["labels"]
                        if lb.get("rescued") and (lb.get("no") or "").strip().isdigit()}
        if _rescued_nos:
            _ss["nums"] = sorted(set(_ss.get("nums", [])) | _rescued_nos,
                                 key=lambda x: int(x) if x.isdigit() else 99)
            _ss["missing"] = sorted(set(_ss.get("missing", [])) - _rescued_nos,
                                    key=lambda x: int(x) if x.isdigit() else 99)
        # 嵌套碎片吸收（R2 起报警留痕）：吸收即不再作为独立器物输出，必须
        # 提示人工复核（002 大钉曾静默吞掉真 6 号小钉/弯钩）
        for host, frags in at.get("absorbed_fragments", {}).items():
            alarms.append({
                "code": "fragment_absorbed",
                "msg": f"⚠ 报警：视图{frags} 被"
                       f"视图{host} 吸收为器内碎片，请复核是否误吸收",
                "host_view": host, "frag_views": frags})
        # 标号冲突：同一视图挂上多个不同序号（连接刻度被误读等）-> 报警待复核
        for lb in at["labels"]:
            if lb.get("_conflict_dropped") is not None:
                alarms.append({
                    "code": "label_conflict",
                    "msg": f"⚠ 报警：序号{lb.get('no')!r}({lb['bbox']}) 与其它序号"
                           f"竞争视图{lb['_conflict_dropped']} 失败被弃用，请复核",
                    "label_bbox": lb["bbox"],
                    "view": lb["_conflict_dropped"]})
        # R7 同号唯一：同一序号多处印刷/误读均获绑定，按 (rank,conf) 只保留
        # 一处（业务规则 K1），弃用者报警待复核
        for lb in at["labels"]:
            if lb.get("_dropped_by_uniqueness"):
                alarms.append({
                    "code": "serial_uniqueness",
                    "msg": f"⚠ 报警：序号{lb.get('no')!r}({lb['bbox']}) 同号多处"
                           f"绑定，按方位/置信择优后弃用此处（同号唯一），请复核",
                    "label_bbox": lb["bbox"]})
        # VL 歧义放弃的孤立视图 -> 报警待复核
        for m in merge_log:
            if m["rule"] == "G3_vl_abandon":
                alarms.append({"code": "orphan_ambiguous",
                               "msg": f"⚠ 报警：孤立视图{m['views']} 归属歧义，"
                                      f"VL 裁决未通过，保持独立待复核",
                               "note": m["note"]})
        # E1.5 VL 二次判定产生的报警（回捞失败/小圆歧义/判定不可用）
        alarms.extend(at.get("alarms_e15", []))
        # 组-序号一致性报警（组内多号 / 号数≠组数）
        alarms.extend(cons_alarms)
        # 像素一致性自检失败 -> 报警（理论上不可能，防回归）
        for g in group_records:
            if g.get("pixel_mismatch"):
                alarms.append({"code": "pixel_mismatch", "group": g["group_id"],
                               "msg": f"⚠ 报警：组{g['seq']} 像素一致性校验失败"
                                      f"（{g['pixel_mismatch']}px）"})

        overlay = self.draw_overlay(bgr, at, groups, bound)
        if overlay is not None:
            ok, buf = cv2.imencode(".png", overlay)
            buf.tofile(os.path.join(out_dir, f"{stem}_overlay.png"))
        if self.review_sheet:                       # E1.5 复核标注图
            self.write_vl_review_sheet(at, stem)
        # --strict-docx：存在报警的图暂停出图（删除已生成 PNG，仅留 JSON 待复核）
        if self.strict_docx and alarms:
            for g in group_records:
                if g.get("output") and os.path.exists(g["output"]):
                    os.remove(g["output"])
                g["output"] = None
                g["withheld"] = "strict_docx: 报警图停发，待复核"
        result = {
            "ok": True, "image": stem, "image_size": list(bgr.shape[1::-1]),
            "n_groups": len(groups), "groups": group_records,
            "merge_log": merge_log, "scales": scale_records,
            "serial_set": _ss,
            "consistency": cons_metrics,
            "absorbed_fragments": at.get("absorbed_fragments", {}),
            "rescued_views": at.get("rescued_views", []),
            "alarms": alarms,
            "vl": {"enabled": self.vl.enabled,
                   "calls": self.vl.n_calls - vl0[0],
                   "success": self.vl.n_success - vl0[1],
                   "failed": self.vl.failed,
                   "records": self.vl.records[vl0[2]:]},
            "latency_s": round(time.time() - t0, 2),
        }
        with open(os.path.join(out_dir, f"{stem}_groups.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        result["_atoms"] = at
        result["_groups_raw"] = groups
        result["_bound"] = bound
        return result

    # ------------------------------------------------------------------
    # 叠加可视化
    # ------------------------------------------------------------------
    def draw_overlay(self, bgr, at, groups, bound):
        vis = (bgr.astype(np.float32) * 0.85 + 255 * 0.15).astype(np.uint8)
        palette = [(228, 26, 28), (55, 126, 184), (77, 175, 74), (152, 78, 163),
                   (255, 127, 0), (166, 86, 40), (247, 129, 191), (0, 160, 160)]
        pil = Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        for gi, g in enumerate(groups):
            color = palette[gi % len(palette)]
            boxes = [at["views"][i]["bbox"] for i in g]
            gb = union_box(boxes)
            for i in g:
                x0, y0, x1, y1 = at["views"][i]["bbox"]
                d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=color, width=3)
            for lb in at["labels"]:
                if lb.get("_attach") is not None and lb["_attach"] in g:
                    x0, y0, x1, y1 = lb["bbox"]
                    d.rectangle([x0, y0, x1, y1], outline=(0, 170, 0), width=2)
            for b in bound[gi]:
                sb = at["scales"][b["si"]]["bbox"]
                d.rectangle(sb, outline=(255, 130, 0), width=3)
                d.line([((gb[0] + gb[2]) // 2, gb[3]), ((sb[0] + sb[2]) // 2, sb[1])],
                       fill=(255, 130, 0), width=2)
            d.text((gb[0] + 2, max(0, gb[1] - 14)),
                   f"G{gi}", fill=color)
        vis = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        return vis


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _collect_images(args):
    base = os.path.dirname(os.path.abspath(__file__))
    if args.all:
        paths = sorted(
            _glob.glob(os.path.join(base, "test_imgs", "*.jpg"))
            + _glob.glob(os.path.join(base, "test_imgs", "*.png")))
        return paths
    if args.sample:
        return [os.path.join(base, "test_imgs", p) for p in SAMPLE_IMAGES]
    return args.paths


def main():
    ap = argparse.ArgumentParser(description="独立器物提取：分组+比例尺绑定+组装")
    ap.add_argument("paths", nargs="*", help="图片路径（可多张）")
    ap.add_argument("--all", action="store_true", help="处理 test_imgs 全部图片")
    ap.add_argument("--sample", action="store_true",
                    help="处理 5 张抽样图（image101/115/246/250/400）")
    ap.add_argument("--out", default="out_extract", help="输出根目录")
    ap.add_argument("--no-vl", action="store_true", help="停用 VL 兜底（纯 CV 规则）")
    ap.add_argument("--strict-docx", action="store_true",
                    help="有报警的图不输出 PNG（docx 严格模式）")
    ap.add_argument("--margin", type=float, default=0.03,
                    help="动态留白比例（0.02-0.05，默认 0.03）")
    ap.add_argument("--keep-serial-digits", action="store_true",
                    help="成品图保留器物序号数字（默认剔除）")
    ap.add_argument("--keep-scale-prefix", action="store_true",
                    help="成品图比例尺保留左侧前缀数字（默认剔除）")
    ap.add_argument("--e1-only", action="store_true",
                    help="分阶段评估：只运行 E1 原子收集 build_atoms"
                         "（E2~E5 注释停用，产物 <stem>_e1.json）")
    ap.add_argument("--e2-only", action="store_true",
                    help="分阶段评估：E1 原子收集（含 E1.5 VL 复核）后只运行"
                         " E2 bind_labels（E3~E5 停用，产物 <stem>_e2.json）")
    ap.add_argument("--e3-only", action="store_true",
                    help="分阶段评估：E1 原子收集（含 E1.5 VL 复核）+ E2 "
                         "bind_labels（+E2.5 回捞，与全流程同口径）后只运行 "
                         "E3 group_views（E4~E5 停用，产物 <stem>_e3.json）")
    ap.add_argument("--e3-no-rescue", action="store_true",
                    help="e3-only 模式跳过 E2.5 回捞（旧口径：与未烘焙回捞的 "
                         "out_e2 输入一致；默认已改为执行回捞以对齐全流程）")
    ap.add_argument("--from-e1", nargs="?", const="out_e1", default=None,
                    metavar="E1_ROOT",
                    help="E2 单独评估复现模式：不重跑 E1，直接读取"
                         " <E1_ROOT>/<stem>/<stem>_e1.json（默认根 out_e1）"
                         " 执行 E2——免 OCR/VL，与 E1 基线完全一致，秒级迭代"
                         "（产物 <stem>_e2.json）")
    ap.add_argument("--from-e2", nargs="?", const="out_e2", default=None,
                    metavar="E2_ROOT",
                    help="E3 单独评估复现模式：不重跑 E1/E2，直接读取"
                         " <E2_ROOT>/<stem>/<stem>_e2.json（默认根 out_e2）"
                         " 中的绑定结果执行 E3——免 OCR/免分割/免 E1.5，与"
                         " out_e2 基线完全一致，秒级迭代（产物 <stem>_e3.json）。"
                         " 默认开启 VL（G3/G4 歧义仲裁需要）；--no-vl 切纯 CV "
                         "快速迭代（VL 触点仍留痕 metrics.vl_touchpoints）")
    ap.add_argument("--src", default="test_imgs",
                    help="源图目录（--from-e1/--from-e2 重算二值墨迹/VL 裁片用，"
                         "默认 test_imgs）")
    ap.add_argument("--vl-review-sheet", action="store_true",
                    help="输出 E1.5 复核标注图 <stem>_vl_review.png"
                         "（VL 判定/报警画回原图，供人工复核）")
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    paths = _collect_images(args)
    # 任务清单：[(stem, path|None, e1_root|None, e2_root|None)]。from-e1/
    # from-e2 复现模式下对应根目录非 None（path 仅用于 stem 推导），路径
    # 缺省时直接遍历根目录下全部 <stem>/<stem>_e{1,2}.json 产物。
    tasks = []
    if args.from_e1 or args.from_e2:
        root_arg = args.from_e1 or args.from_e2
        replay_root = root_arg if os.path.isabs(root_arg) \
            else os.path.join(base, root_arg)
        src_dir = args.src
        if not os.path.isabs(src_dir):
            src_dir = os.path.join(base, src_dir)
        if paths:
            for p in paths:
                tasks.append((os.path.splitext(os.path.basename(p))[0],
                              p,
                              replay_root if args.from_e1 else None,
                              replay_root if args.from_e2 else None))
        else:
            pat = "*_e1.json" if args.from_e1 else "*_e2.json"
            for jp in sorted(_glob.glob(os.path.join(replay_root, "*", pat))):
                tasks.append((os.path.basename(os.path.dirname(jp)),
                              None,
                              replay_root if args.from_e1 else None,
                              replay_root if args.from_e2 else None))
    else:
        src_dir = None
        for p in paths:
            tasks.append((os.path.splitext(os.path.basename(p))[0], p, None, None))
    if not tasks:
        ap.print_help()
        return
    if args.from_e1 or args.from_e2:
        # 复现模式：只用 bbox/读值/绑定结果，不触 OCR——用参数桩替代
        # ArcheaRec（免 paddleocr 初始化，迭代更快）。
        # VL：from-e2（E3）默认开启（G3/G4 歧义仲裁真实需要），--no-vl
        # 切纯 CV 快速迭代；from-e1（E2）无需 VL，固定关闭。
        from archea_rec import DEFAULTS as _REC_DEFAULTS

        class _NoOcrRec:
            p = dict(_REC_DEFAULTS)

        rec_stub = _NoOcrRec()
        vl_on = (not args.no_vl) if args.from_e2 else False
    else:
        rec_stub, vl_on = None, not args.no_vl
    ex = ArcheaExtract(out_root=args.out, vl=vl_on,
                       strict_docx=args.strict_docx, margin_pct=args.margin,
                       strip_serial_digits=not args.keep_serial_digits,
                       strip_scale_prefix=not args.keep_scale_prefix,
                       e1_only=args.e1_only,
                       e2_only=args.e2_only or bool(args.from_e1),
                       e3_only=args.e3_only or bool(args.from_e2),
                       # from-e2 重放的 out_e2 已烘焙 E2.5 回捞结果，不再执行
                       e3_rescue=(not args.e3_no_rescue)
                                 and not bool(args.from_e2),
                       rec=rec_stub,
                       review_sheet=args.vl_review_sheet)
    batch = []
    for stem, p, e1_root, e2_root in tasks:
        print(f"=== {stem} ===", flush=True)
        if e2_root is not None:
            # E3 单独评估复现模式：跳过 E1/E2（OCR/分割/E1.5），直接读
            # E2 产物中的绑定结果执行 E3
            try:
                res = ex.extract_e3_from_e2(stem, e2_root=e2_root,
                                            src_dir=src_dir)
            except FileNotFoundError:
                print(f"  跳过：{e2_root}/{stem}/{stem}_e2.json 不存在",
                      flush=True)
                continue
        elif e1_root is not None:
            # E2 单独评估复现模式：跳过 E1（OCR/VL/分割），直接读 E1 产物
            try:
                res = ex.extract_e2_from_e1(stem, e1_root=e1_root,
                                            src_dir=src_dir)
            except FileNotFoundError:
                print(f"  跳过：{e1_root}/{stem}/{stem}_e1.json 不存在",
                      flush=True)
                continue
        else:
            res = ex.extract_image(p, stem=stem)
        res.pop("_atoms", None)
        res.pop("_groups_raw", None)
        res.pop("_bound", None)
        batch.append({k: v for k, v in res.items() if k != "groups"} | {
            "groups": [{kk: vv for kk, vv in g.items() if kk != "members"}
                       for g in res.get("groups", [])]})
        n_alarm = len(res.get("alarms", []))
        print(f"  groups={res.get('n_groups')} alarms={n_alarm} "
              f"vl={res['vl']['success']}/{res['vl']['calls']} "
              f"latency={res.get('latency_s')}s", flush=True)
        if res.get("stage") == "E1_only":
            print(f"  E1: views={res.get('n_views')}"
                  f"(救援{res.get('n_rescued')}) labels={res.get('n_labels')} "
                  f"prefixes={res.get('n_prefixes')} links={res.get('n_links')} "
                  f"scales={res.get('n_scales')} others={res.get('n_others')} "
                  f"absorbed={res.get('n_absorbed')}", flush=True)
            if res.get("n_vl_review"):
                print(f"  E1.5: vl_review={res.get('n_vl_review')}"
                      f"(回捞{res.get('n_vl_rescued')}) "
                      f"e15报警={res.get('n_alarms_e15')}", flush=True)
        if res.get("stage") == "E2_only":
            rate = res.get("assign_rate")
            rate_s = f"({rate * 100:.1f}%)" if rate is not None else ""
            print(f"  E2: 序号={res.get('n_labels')} "
                  f"绑定成功={res.get('n_assigned')}{rate_s}", flush=True)
            print(f"      无候选={res.get('n_no_candidate')} "
                  f"冲突弃用={res.get('n_conflict')} "
                  f"内部让位={res.get('n_inner_yielded')} | "
                  f"视图={res.get('n_views')}"
                  f"(有号 {res.get('n_views_labeled')}/"
                  f"无号 {res.get('n_views_unlabeled')})", flush=True)
            if res.get("n_links"):
                print(f"      连接符={res.get('n_links')} "
                      f"继承={res.get('n_inherited')}"
                      f"({res.get('n_inherited_views')}视图) "
                      f"继承后无号视图={res.get('n_views_unlabeled_after')}",
                      flush=True)
            if res.get("set_nums_unbound"):
                print(f"      序号集未绑定: {res.get('set_nums_unbound')}",
                      flush=True)
            if res.get("bound_nos_not_in_set"):
                print(f"      绑定序号不在序号集: "
                      f"{res.get('bound_nos_not_in_set')}", flush=True)
        if res.get("stage") == "E3_only":
            m = res.get("metrics", {})
            hist_s = " ".join(f"{k}×{v}" for k, v in
                              sorted(res.get("group_size_hist", {}).items()))
            rules_s = " ".join(f"{k}×{v}" for k, v in
                               res.get("rule_counts", {}).items())
            print(f"  E3: 视图={res.get('n_views')} -> 组={res.get('n_groups')}"
                  f"  规模[{hist_s}]", flush=True)
            if rules_s:
                print(f"      合并规则: {rules_s}", flush=True)
            print(f"      带号组={m.get('n_groups_labeled')} "
                  f"无号组={m.get('n_groups_unlabeled')} "
                  f"多号可疑组={res.get('n_multi_no_groups')} "
                  f"孤立无号组={res.get('n_orphan_groups')} "
                  f"VL触点={res.get('vl_touchpoints')} "
                  f"VL放弃={res.get('n_vl_abandon')}", flush=True)
            for g in res.get("groups", []):
                ins = g.get("label_nos_inside") or []
                inh = g.get("label_nos_inherited") or []
                print(f"    G{g['group_id']}: views={g['view_ids']} "
                      f"nos={g['label_nos']}"
                      + (f" +内{ins}" if ins else "")
                      + (f" +继承{inh}" if inh else ""), flush=True)
        for a in res.get("alarms", []):
            print(f"  {a['msg']}", flush=True)
        if res.get("stage") != "E3_only":          # E3 已逐组打印（无出图/比例尺）
            for g in res.get("groups", []):
                print(f"  -> {g.get('output')} nos={g.get('label_nos')} "
                      f"scales={[(s['text'], s['source']) for s in g.get('scales', [])]}",
                      flush=True)
    if len(batch) > 1 or args.all or args.sample:
        sp = os.path.join(args.out, "batch_summary.json")
        os.makedirs(args.out, exist_ok=True)
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump({"n_images": len(batch), "results": batch,
                       "vl_total_calls": ex.vl.n_calls,
                       "vl_total_success": ex.vl.n_success,
                       "vl_failed": ex.vl.failed}, fh,
                      ensure_ascii=False, indent=2)
        print(f"批量汇总: {sp}")


if __name__ == "__main__":
    main()

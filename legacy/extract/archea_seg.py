#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ============================================================================
# archea_seg.py - 考古器物实例分割（自完备模块，仅分割识别，无展示能力）。
#
# 项目背景：
#   test_imgs 中的线图通常包含多个考古器物，同一器物可能以多个视角
#   （俯视图、侧视图等）出现；器物图下方常伴有比例尺。本模块负责
#   流水线的前半段--实例级分割；识别结果交给下游 VL 模型判断哪些
#   实例属于同一器物（依据序号、空间聚集、器物相似性等高/等宽等），
#   并与对应比例尺绑定。
#
# 自完备说明：
#   本模块不依赖 sam_seg.py / verify_contour_sam.py 等外部项目文件，
#   处理链路（与 verify_contour_sam.py 语义一致）全部内联实现：
#     1) 灰度 -> OTSU 二值化（线稿黑线转前景）-> 形态学膨胀；
#     2) cv2.findContours 提取轮廓；包含关系判定去除内部孔洞/内含小轮廓；
#     3) 保留轮廓内部腐蚀区采样正点 + 质心正点 + 外环负点，作为
#        Point Prompt 逐轮廓调 SAM3 服务精分割（协议：POST /predict，
#        multipart image + points(JSON)；
#        输入为路径时直接上传原始文件字节）；
#     4) 逐轮廓挑选与轮廓填充区 IoU 最优的 SAM 掩膜。
#
# 图片输入格式（segment(image) 的 image 参数）：
#   - 文件路径（str/os.PathLike）：支持 png / jpg / jpeg / bmp / webp /
#     tif / tiff 等OpenCV 可解码格式，且对中文路径安全（np.fromfile + imdecode）；
#   - bytes / bytearray：图片文件的原始字节（格式自动识别）；
#   - numpy.ndarray：BGR 图像（cv2 语义）。
#
# 类：ArcheaSeg
#   构造  ArcheaSeg(service="http://159.226.29.162:8004", dilate_k=5,
#                   min_area=200.0, n_points=24, n_neg=24,
#                   max_side=None, timeout=120.0)
#                   max_side: 裁剪图最长边上限（None 不缩放），
#                             控制 VL 模型输入的 token 体积。
#   入口  segment(image, seed_base=0) -> dict
#         seed_base: 逐轮廓随机种子基数（seed = seed_base + cid），
#                     固定 seed_base 可复现采样。
#
# 输出 dict（实例字段均可直接喂给 VL 模型）：
#   {
#     "ok": bool, "error": str|None,
#     "image_size": [W, H],            # 原图尺寸
#     "instances": [                   # 实例列表（阅读序：上->下、左->右；
#                                      #   一个 CV 轮廓可能对应多个实例）
#       {
#         "id": int,                   # 实例序号（全局递增）
#         "rank": int,                 # 同一 CV 轮廓内的子实例序号
#                                      #   （SAM 拆分出刃/柄等部位时 >0；
#                                      #    是否同一器物由下游 VL 判断）
#         "bbox": [x0, y0, x1, y1],    # 所属 CV 轮廓包围盒
#         "bbox_sam": [x0,y0,x1,y1],   # SAM 预测框（像素坐标）
#         "center": [cx, cy],          # 所属轮廓质心（空间聚集判断）
#         "area": float,               # 轮廓面积（px^2）
#         "width": int, "height": int, # bbox 宽高（等宽/等高相似性判断）
#         "score": float,              # SAM 对象分数
#         "iou_with_contour": float,   # SAM 掩膜与轮廓填充区 IoU
#         "mask_base64": str|None,     # SAM 掩膜 PNG（原分辨率）
#         "crop_base64": str|None,     # 实例裁剪图 PNG（bbox 区域，
#                                      #     max_side 缩放后）--VL 模型输入
#         "mask_on_crop_base64": str|None,  # 裁剪图 + 掩膜高亮叠图（PNG）
#         "contour_poly": [[x,y],...], # 所属轮廓简化多边形（回放/调试）
#         "sam_ok": bool, "sam_error": str|None
#       }, ...
#     ],
#     "stats": {"n_instances": int, "n_sam_ok": int,
#               "latency_s": float}
#   }
#
# 提示（下游聚合可用的信号，本模块不实现聚合）：
#   - 空间聚集：instance.center 的邻近关系（多视角常横向/纵向成组）；
#   - 相似性：width/height 或 bbox 宽高比接近（等高/等宽）；
#   - 比例尺：细长、极宽（w>>h）的小面积实例是比例尺候选，可据 bbox
#     形状初筛后由 VL 模型确认并与器物绑定。
#
# 用法示例：
#   from archea_seg import ArcheaSeg
#   seg = ArcheaSeg()
#   result = seg.segment("test_imgs/002.png")        # 路径（png/jpg/jpeg/...）
#   result = seg.segment(open("a.jpg", "rb").read()) # 图片原始字节
#   for inst in result["instances"]:
#       print(inst["id"], inst["bbox"], inst["center"], inst["sam_ok"])
#
# 依赖（仅需第三方库 cv2/numpy/PIL/requests）：
#   pip install opencv-python numpy pillow requests
# ============================================================================
"""考古器物实例分割：CV 轮廓 + SAM3 精分割，输出结构化实例（自完备、无展示）。"""

import base64
import io
import json
import os
import time

import cv2
import numpy as np
import requests
from PIL import Image


# ---------------------------------------------------------------------------
# 模块级工具：图片读取（多格式 + 中文路径安全）
# ---------------------------------------------------------------------------
def decode_image_bytes(data):
    """图片原始字节 -> BGR ndarray（格式自动识别：png/jpg/jpeg/bmp/webp/tif...）。"""
    arr = np.frombuffer(bytes(data), dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def load_image(image):
    """多形态输入 -> (BGR ndarray | None, 上传字节 | None)。

    支持：文件路径（任何 OpenCV 可解码格式，中文路径安全）、
    bytes/bytearray（图片原始字节）、BGR ndarray。
    返回的上传字节用于 SAM 服务（路径输入时为原始文件字节）。
    """
    if isinstance(image, (str, os.PathLike)):
        path = os.fspath(image)
        data = open(path, "rb").read()  # 原始文件字节（直接上传，与路径输入一致）
        return decode_image_bytes(data), data
    if isinstance(image, (bytes, bytearray)):
        return decode_image_bytes(image), bytes(image)
    if isinstance(image, np.ndarray):
        return np.ascontiguousarray(image), None
    return None, None


def _png_base64(bgr_or_rgb):
    """ndarray -> PNG base64（无需落盘）。"""
    ok, buf = cv2.imencode(".png", bgr_or_rgb)
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _mask_png_base64(mask):
    """bool 掩膜 -> 单通道 PNG base64（与 SAM 服务返回格式一致）。"""
    return _png_base64(np.where(mask, 255, 0).astype(np.uint8))


def _mask_box(mask):
    """bool 掩膜 -> [x0, y0, x1, y1]（像素坐标，与 SAM box 同义）。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return [0, 0, 0, 0]
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def _resize_max_side(img, max_side):
    """最长边缩放到 max_side（None 或不超限则原样返回）。"""
    if not max_side or max(img.shape[:2]) <= max_side:
        return img
    scale = max_side / max(img.shape[:2])
    return cv2.resize(img, (int(round(img.shape[1] * scale)),
                            int(round(img.shape[0] * scale))),
                      interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------------
# CV + SAM 处理原语（语义与 verify_contour_sam.py 一致，自完备内联实现）
# ---------------------------------------------------------------------------
def extract_contours(gray, dilate_k=5, min_area=200.0):
    """二值化->膨胀->findContours->包含关系去除。

    返回 (kept, removed, binary)。去除规则：①连通域内部孔洞（hierarchy 有父）；
    ②小轮廓 bbox 四角均落在某更大轮廓多边形内（pointPolygonTest >= 0）。
    """
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_k, dilate_k))
    dilated = cv2.dilate(binary, kernel, iterations=1)
    contours, hierarchy = cv2.findContours(
        dilated, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    hier = hierarchy[0] if hierarchy is not None else np.empty((0, 4), dtype=np.int32)

    cands = []
    for i, c in enumerate(contours):
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        is_hole = hier[i][3] != -1  # 有父轮廓 = 孔洞/内含
        x, y, w, h = cv2.boundingRect(c)
        cands.append({"bbox": (x, y, x + w, y + h), "area": area,
                      "contour": c, "hole": is_hole})

    kept, removed = [], []
    for item in cands:
        if item["hole"]:
            removed.append(item)
            continue
        contained = False
        for other in cands:
            if other is item or other["hole"] or other["area"] <= item["area"]:
                continue
            x0, y0, x1, y1 = item["bbox"]
            corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
            if all(cv2.pointPolygonTest(other["contour"], (float(px), float(py)),
                                        False) >= 0 for px, py in corners):
                contained = True
                break
        (removed if contained else kept).append(item)
    kept.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))  # 阅读序：上->下、左->右
    return kept, removed, dilated


def contour_to_points(contour, n):
    """轮廓等弧长采样为 [[x,y,1],...] 正点序列（细长形退化用）。"""
    pts = contour.reshape(-1, 2).astype(float)
    if len(pts) < 3:
        return [[int(round(pts[0][0])), int(round(pts[0][1])), 1]]
    closed = np.vstack([pts, pts[:1]])
    seg = np.sqrt(((np.diff(closed, axis=0)) ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return [[int(round(pts[0][0])), int(round(pts[0][1])), 1]]
    out = []
    for t in np.linspace(0, total, n, endpoint=False):
        i = min(int(np.searchsorted(cum, t, side="right")) - 1, len(seg) - 1)
        r = (t - cum[i]) / seg[i] if seg[i] > 0 else 0.0
        p = closed[i] * (1 - r) + closed[i + 1] * r
        out.append([int(round(p[0])), int(round(p[1])), 1])
    return out


def filled_mask(contour, shape):
    """轮廓填充掩膜（0/1），作为轮廓的区域表达与 IoU 基准。"""
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [contour], 1)
    return m


def mask_iou(a, b):
    inter = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    return inter / union if union else 0.0


def contour_prompt(contour, shape, n_pos=12, n_neg=12, seed=0):
    """轮廓 -> point prompt：按最大外围填充区采样正点 + 外环负点 + 质心正点。

    策略（保证器物"外部"识别优先，内部细节留给后续切分）：
    正点采样域取 CV 轮廓的最大外围（fillPoly 全域，含内部空洞区），
    仅腐蚀 1px（3x3 核）避开边界歧义--细长部（宽约 20px 的柄/梁）
    与窄连接线区域也能采到正点，SAM 更倾向切出完整外围；
    负点取外环。边界点对 SAM 有歧义（易选中背景/补集），故不采。
    """
    rng = np.random.default_rng(seed)
    filled = filled_mask(contour, shape)
    points = []
    m = cv2.moments(contour)
    if m["m00"] > 0:
        points.append([int(round(m["m10"] / m["m00"])),
                       int(round(m["m01"] / m["m00"])), 1])
    inner = cv2.erode(filled, np.ones((3, 3), np.uint8))  # 1px：细长部可采
    ys, xs = np.nonzero(inner)
    if len(xs) >= 4:
        for j in rng.choice(len(xs), min(n_pos, len(xs)), replace=False):
            points.append([int(xs[j]), int(ys[j]), 1])
    else:
        points.extend(contour_to_points(contour, n_pos))
    ring = cv2.dilate(filled, np.ones((9, 9), np.uint8)) - filled
    ys2, xs2 = np.nonzero(ring)
    if len(xs2):
        for j in rng.choice(len(xs2), min(n_neg, len(xs2)), replace=False):
            points.append([int(xs2[j]), int(ys2[j]), 0])
    return points


def call_sam_points(service, upload_bytes, filename, points, timeout):
    """POST /predict：multipart image（原始字节）+ points(JSON)。"""
    files = {"image": (filename or "image.png", io.BytesIO(upload_bytes),
                       "application/octet-stream")}
    data = {"points": json.dumps(points)}
    resp = requests.post(f"{service.rstrip('/')}/predict",
                         files=files, data=data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def decode_mask(b64):
    """SAM 掩膜 PNG base64 -> PIL Image（L 模式）。"""
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("L")


def contour_poly(contour, eps=1.0):
    """approxPolyDP 简化轮廓多边形，供 JSON 保留与回放。"""
    approx = cv2.approxPolyDP(contour, eps, True)
    return [[int(px), int(py)] for px, py in approx.reshape(-1, 2)]


def merge_candidate_masks(scored, filled, rel_iou=0.1):
    """[已弃用，保留备查] 相关候选掩膜贪心合并。

    当前阶段目标是实例级分割：SAM 把一个器物拆成多个对象（如刃/柄）
    时应保留为多个独立实例，由下游 VL 模型判断是否同一器物，不合并。
    """
    if not scored:
        return 0.0, None
    rel = [t for t in scored if t[0] > rel_iou]
    if not rel:
        rel = [scored[0]]
    best_iou, merged = rel[0][0], rel[0][2].copy()
    for iou, _score, m in rel[1:]:
        cand = merged | m
        cand_iou = mask_iou(cand, filled)
        if cand_iou > best_iou:
            merged, best_iou = cand, cand_iou
    return best_iou, merged


def merge_overlapping_instances(entries, overlap_frac=0.1):
    """重合/相交实例合并（全局后处理）。

    掩膜存在交集（交集面积 / 较小实例面积 > overlap_frac）的实例
    合并为一个（并集掩膜），合并前的小实例被吸收删除，score 取最大。
    完全不相交的实例保持独立（如 SAM 拆出的刃部/柄部）。

    entries: [{"item": 轮廓dict, "score": float, "mask": bool ndarray}, ...]
    返回合并后的新列表（按掩膜面积降序；调用方可再按需排序）。
    """
    entries = [dict(e) for e in entries]
    changed = True
    while changed:
        changed = False
        entries.sort(key=lambda e: int(e["mask"].sum()), reverse=True)
        for i in range(len(entries)):
            for j in range(len(entries) - 1, i, -1):
                a, b = entries[i]["mask"], entries[j]["mask"]
                inter = int(np.logical_and(a, b).sum())
                if inter and inter / min(int(a.sum()), int(b.sum())) > overlap_frac:
                    # 小实例并入大实例（并集），小实例删除
                    entries[i]["mask"] = a | b
                    entries[i]["score"] = max(entries[i]["score"], entries[j]["score"])
                    entries.pop(j)
                    changed = True
    return entries


class ArcheaSeg:
    """考古器物实例分割（仅分割识别；展示/聚合/绑定由下游负责）。"""

    def __init__(self, service="http://159.226.29.162:8004", dilate_k=5,
                 min_area=2.0, n_points=24, n_neg=24,
                 max_side=None, timeout=120.0, rel_iou=0.1, nms_iou=0.5,
                 overlap_frac=0.1):
        self.service = service.rstrip("/")
        self.dilate_k = dilate_k
        self.min_area = min_area
        self.n_points = n_points
        self.n_neg = n_neg
        self.max_side = max_side
        self.timeout = timeout
        # 相关候选阈值：与轮廓填充区 IoU 超过该值的 SAM 候选视为属于该轮廓
        self.rel_iou = rel_iou
        # NMS 阈值：候选间 IoU 超过该值视为同一部位（保留分高的），去重
        self.nms_iou = nms_iou
        # 相交合并阈值：实例掩膜交集占较小实例面积超过该值时合并
        # （小实例被吸收删除；完全不相交的保持独立，如刃部/柄部）
        self.overlap_frac = overlap_frac

    # ------------------------------------------------------------------
    # 主入口：一张图 -> 结构化实例列表
    # ------------------------------------------------------------------
    def segment(self, image, seed_base=0):
        """实例分割。image 支持 路径/bytes/BGR ndarray；返回见模块头注释。"""
        t0 = time.time()
        bgr, upload_bytes = load_image(image)
        if bgr is None:
            return self._fail("imread failed", time.time() - t0)
        filename = (os.path.basename(os.fspath(image))
                    if isinstance(image, (str, os.PathLike)) else "image.png")
        if upload_bytes is None:  # ndarray 输入：编码 PNG 上传
            ok, buf = cv2.imencode(".png", bgr)
            if not ok:
                return self._fail("imencode failed", time.time() - t0)
            upload_bytes = buf.tobytes()

        h, w = bgr.shape[:2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        kept, _removed, _ = extract_contours(gray, self.dilate_k, self.min_area)

        # 第一阶段：逐轮廓调用 SAM，收集全部子实例（含掩膜）
        raw = []  # [{"item", "score", "mask"}]
        failed_items = []  # SAM 完全失败的轮廓（CV 兜底实例）
        for item in kept:
            points = contour_prompt(item["contour"], gray.shape,
                                    self.n_points, self.n_neg,
                                    seed=seed_base + len(raw))
            sub_objs = self._segment_contour(bgr, gray.shape, item, points,
                                             upload_bytes, filename)
            ok_objs = [s for s in sub_objs if s.get("ok")]
            if not ok_objs:
                failed_items.append(item)
                continue
            for sam in ok_objs:
                mask = np.asarray(decode_mask(sam["mask_base64"]).resize(
                    (w, h), Image.NEAREST), dtype=bool)
                raw.append({"item": item, "score": sam["score"], "mask": mask,
                            "contour_mask": filled_mask(item["contour"],
                                                        gray.shape)})

        # 第二阶段：全局相交合并（重合实例并集，小实例吸收删除）
        merged = merge_overlapping_instances(raw, self.overlap_frac)

        # 第三阶段：生成最终实例（重新编号，计算 IoU/box/裁剪图）
        instances = []
        for entry in merged:
            item, mask = entry["item"], entry["mask"]
            sam = {"ok": True, "score": entry["score"],
                   "iou_with_contour": round(mask_iou(
                       mask, filled_mask(item["contour"], gray.shape)), 3),
                   "box": _mask_box(mask),
                   "mask_base64": _mask_png_base64(mask)}
            inst = self._base_instance(len(instances), item, rank=0)
            inst["sam_ok"] = True
            inst["score"] = sam["score"]
            inst["iou_with_contour"] = sam["iou_with_contour"]
            inst["bbox_sam"] = sam["box"]
            inst["mask_base64"] = sam["mask_base64"]
            # 对应的 extract_contours 保留轮廓掩膜（同色系对照用）
            if entry.get("contour_mask") is not None:
                inst["contour_mask_base64"] = _mask_png_base64(
                    entry["contour_mask"].astype(bool))
            inst.update(self._crops(bgr, item, sam))
            instances.append(inst)

        # SAM 失败轮廓的 CV 兜底实例
        for item in failed_items:
            inst = self._base_instance(len(instances), item, rank=0)
            inst["sam_error"] = "no objects"
            inst["contour_mask_base64"] = _mask_png_base64(
                filled_mask(item["contour"], gray.shape).astype(bool))
            inst.update(self._crops(bgr, item, {"ok": False}))
            instances.append(inst)

        n_ok = sum(1 for i in instances if i["sam_ok"])
        return {
            "ok": True, "error": None,
            "image_size": [w, h],
            "instances": instances,
            "stats": {"n_instances": len(instances), "n_sam_ok": n_ok,
                      "latency_s": round(time.time() - t0, 3)},
        }

    # ------------------------------------------------------------------
    # 内部：失败返回 / SAM 单轮廓 / 实例字段 / 裁剪图
    # ------------------------------------------------------------------
    @staticmethod
    def _fail(error, elapsed):
        return {"ok": False, "error": error, "image_size": None,
                "instances": [], "stats": {"n_instances": 0, "n_sam_ok": 0,
                                           "latency_s": round(elapsed, 3)}}

    def _segment_contour(self, bgr, shape, item, points, upload_bytes, filename):
        """对单个 CV 轮廓调用 SAM3，返回该轮廓的独立子实例列表。

        当前阶段目标：实例级分割。SAM 语义上把一个器物拆成多个对象
        （如刃部/柄部）时，各对象保留为独立实例，由下游 VL 模型判断
        是否属于同一器物。实现：取与轮廓填充区相关的候选
        （IoU > rel_iou），按重叠度 NMS 去重（IoU > nms_iou 的候选
        视为同一部位，保留分高的），每个存活候选一个子实例。
        """
        pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        filled = filled_mask(item["contour"], shape).astype(bool)
        try:
            data = call_sam_points(self.service, upload_bytes, filename,
                                   points, self.timeout)
            objs = data.get("objects", [])
            if not objs:
                return []
            scored = []
            for o in objs:
                om = np.asarray(decode_mask(o["mask_base64"]).resize(
                    pil.size, Image.NEAREST), dtype=bool)
                scored.append((mask_iou(om, filled), o["score"], o, om))
            # 相关候选：与该轮廓填充区有明显重叠；全都不相关时取最优兜底
            rel = [t for t in scored if t[0] > self.rel_iou]
            if not rel:
                rel = [max(scored, key=lambda t: (t[0], t[1]))]
            # NMS 前排序：与 CV 轮廓（最大外围）IoU 优先，其次 SAM score
            # --外部优先策略：覆盖完整外围的候选优先保留，高分但只覆盖
            # 局部（如长条器物的中段细条）的候选被抑制
            rel.sort(key=lambda t: (t[0], t[1]), reverse=True)
            # NMS：候选间 IoU 超过 nms_iou 视为同一部位，去重
            kept_objs = []
            for iou, score, o, om in rel:
                dup = False
                for _i2, _s2, _o2, om2 in kept_objs:
                    inter = np.logical_and(om, om2).sum()
                    union = np.logical_or(om, om2).sum()
                    if union and inter / union > self.nms_iou:
                        dup = True
                        break
                if not dup:
                    kept_objs.append((iou, score, o, om))
            out = []
            for iou, score, o, om in kept_objs:
                out.append({
                    "ok": True,
                    "score": round(score, 3),
                    "iou_with_contour": round(iou, 3),
                    "box": _mask_box(om),
                    "latency_s": data.get("latency_s"),
                    "mask_base64": _mask_png_base64(om),
                })
            return out
        except Exception as e:
            return [{"ok": False, "error": f"{type(e).__name__}: {e}"}]

    @staticmethod
    def _base_instance(cid, item, rank=0):
        x0, y0, x1, y1 = item["bbox"]
        m = cv2.moments(item["contour"])
        center = ([int(round(m["m10"] / m["m00"])),
                   int(round(m["m01"] / m["m00"]))] if m["m00"] > 0
                  else [(x0 + x1) // 2, (y0 + y1) // 2])
        return {
            "id": cid,
            "rank": rank,  # 同一 CV 轮廓内的子实例序号（SAM 拆分出多个部位时 >0）
            "bbox": [x0, y0, x1, y1],
            "bbox_sam": None,
            "center": center,
            "area": round(item["area"], 1),
            "width": x1 - x0, "height": y1 - y0,
            "score": None, "iou_with_contour": None,
            "mask_base64": None, "crop_base64": None,
            "mask_on_crop_base64": None,
            "contour_poly": contour_poly(item["contour"]),
            "sam_ok": False, "sam_error": None,
        }

    def _crops(self, bgr, item, sam):
        """实例裁剪图（VL 输入）与掩膜高亮叠图，均 max_side 限边。

        裁剪区域取 CV bbox 与 SAM box 的并集（若 SAM 成功），既保证
        完整器物又略带上下文；SAM 失败时退回 CV bbox。
        """
        x0, y0, x1, y1 = item["bbox"]
        if sam.get("ok") and sam.get("box"):
            sx0, sy0, sx1, sy1 = sam["box"]
            x0, y0 = min(x0, sx0), min(y0, sy0)
            x1, y1 = max(x1, sx1), max(y1, sy1)
        h, w = bgr.shape[:2]
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(w, int(x1)), min(h, int(y1))
        if x1 <= x0 or y1 <= y0:
            return {"crop_base64": None, "mask_on_crop_base64": None}
        crop = bgr[y0:y1, x0:x1]
        crop = _resize_max_side(crop, self.max_side)
        out = {"crop_base64": _png_base64(crop)}

        if sam.get("ok") and sam.get("mask_base64"):
            mask = np.asarray(decode_mask(sam["mask_base64"]).resize(
                (w, h), Image.NEAREST), dtype=bool)
            overlay = bgr.copy()
            overlay[mask] = (overlay[mask] * 0.5).astype(np.uint8)
            vis = overlay[y0:y1, x0:x1]
            vis = _resize_max_side(vis, self.max_side)
            out["mask_on_crop_base64"] = _png_base64(vis)
        return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python archea_seg.py <image_path> [service]")
        sys.exit(1)
    path = sys.argv[1]
    svc = sys.argv[2] if len(sys.argv) > 2 else "http://159.226.29.162:8004"
    seg = ArcheaSeg(service=svc)
    res = seg.segment(path)
    # 摘要打印（掩膜/裁剪图 base64 太长，不全量打印）
    print(json.dumps({
        "ok": res["ok"], "image_size": res["image_size"],
        "stats": res["stats"],
        "instances": [{k: v for k, v in inst.items()
                       if k not in ("mask_base64", "crop_base64",
                                    "mask_on_crop_base64", "contour_poly")}
                      for inst in res["instances"]],
    }, ensure_ascii=False, indent=2))

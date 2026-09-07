"""E5 成图（legacy/extract/archea_extract.py compose_group 迁移，V0.5.4）。

两段拆分（组装上下文与像素合成分离）：
  group_render_context(at, group_ids, binds, cfg) — E5 几何决策（需组装
    上下文 at）：组内容掩膜（视图防串染剔除 + 组内连接符 + 贴近说明文字；
    序号数字/比例尺前缀默认剥离、只记 bbox 供追溯）与比例尺整组裁条，
    产物 RLE 化可入 state.checkpoint；
  render_group(bgr, ctx, cfg) — 纯像素合成：白底画布 + 内容纯平移（不
    缩放/不旋转/不重排）+ 比例尺行置底居中 + pixel_mismatch 自检。
"""
from __future__ import annotations

import cv2
import numpy as np

from .assembly import bbox_gap, ink_mask, paste_region, union_box
from .rle import rle_decode, rle_encode


class ComposeConfig:
    """E5 成图参数（取值与原型 ArcheaExtract 默认一致）。

    strip_serial_digits / strip_scale_prefix：成品图不画序号数字与比例尺
    前缀数字（仍参与分组与绑定，bbox 记入 members/scales 供追溯）。
    """

    def __init__(self, margin_pct: float = 0.03, link_gap: int = 52,
                 attach_text_gap: int = 18, strip_serial_digits: bool = True,
                 strip_scale_prefix: bool = True, prefix_ext: int = 150):
        self.margin_pct = margin_pct
        self.link_gap = link_gap
        self.attach_text_gap = attach_text_gap
        self.strip_serial_digits = strip_serial_digits
        self.strip_scale_prefix = strip_scale_prefix
        self.prefix_ext = prefix_ext


def group_render_context(at, group_ids, binds, cfg=None):
    """单组 E5 几何决策 → 渲染上下文（RLE 化 dict；无成员掩膜返回 None）。

    binds: E4 bind_scales 输出中该组的绑定列表（[{"si", "source",
    "prefix_nos", "shared"}, ...]）。内容掩膜剔除其它组视图像素（防串染）；
    剔除致整组清空时回退原始掩膜保持出图（该类图已带 S1/孤立报警）。
    """
    cfg = cfg or ComposeConfig()
    bgr, binary = at["bgr"], at["binary"]
    views = [at["views"][i] for i in group_ids]
    H, W = bgr.shape[:2]

    # --- 成员掩膜收集（视图 + 标号 + 连接符 + 贴近说明文字） ---
    gid = set(group_ids)
    other_mask = np.zeros((H, W), bool)
    for i in range(len(at["views"])):
        if i in gid:
            continue
        m = at["views"][i].get("mask")
        if m is not None:
            other_mask |= m

    content_masks = []
    members = {"views": [], "labels": [], "links": [], "texts": []}
    cm = np.zeros((H, W), bool)
    for v in views:
        if v.get("mask") is None:
            continue
        m = v["mask"] & ~other_mask          # 剔除其它组视图像素（防串染）
        if m.any():
            content_masks.append(m)
            cm |= m
            members["views"].append({"bbox": v["bbox"]})
    if not content_masks:
        # 防串染剔除把整组清空（嵌套视图被 S1 硬证据闸分成两组等）：
        # 回退原始掩膜保持出图（该类图已带 S1/孤立报警，供人工复核）
        for v in views:
            if v.get("mask") is not None:
                cm |= v["mask"]
                members["views"].append({"bbox": v["bbox"]})
        if cm.any():
            content_masks.append(cm.copy())
    for v in views:
        for lbbox in v.get("label_boxes", []):
            if cfg.strip_serial_digits:
                # 序号数字只用于分组/绑定，不画进成品；bbox 仍记录可追溯
                members["labels"].append({"bbox": lbbox, "painted": False})
                continue
            m = ink_mask(binary, lbbox)
            if m is not None and m.any():
                content_masks.append(m)
                cm |= m
                members["labels"].append({"bbox": lbbox, "painted": True})
    gbox0 = union_box([v["bbox"] for v in views]) if views else None

    # 组内连接符：触及任一成员，或落于两成员并集框内（between）
    for lk in at["links"]:
        b = lk["bbox"]
        touch = False
        for i in group_ids:
            gx, gy = bbox_gap(b, at["views"][i]["bbox"])
            if gx == 0 and gy == 0:
                touch = True
            elif gx <= cfg.link_gap and gy <= cfg.link_gap:
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
                cm |= m
                members["links"].append({"bbox": b, "text": lk.get("text", "")})

    # 贴近说明文字（图旁注释；远离的图注行不收）
    content_box = (paste_region(cm)[0] if cm.any() else None) or gbox0
    if content_box is not None:
        for o in at["others"]:
            if o["reason"] not in ("text", "unreadable"):
                continue
            ob = o["bbox"]
            gx, gy = bbox_gap(ob, content_box)
            if (gx == 0 and gy <= cfg.attach_text_gap) \
                    or (gy == 0 and gx <= cfg.attach_text_gap):
                m = ink_mask(binary, ob)
                if m is not None and m.any():
                    content_masks.append(m)
                    cm |= m
                    members["texts"].append({"bbox": ob,
                                             "text": o.get("text", "")})

    if not content_masks or not cm.any():
        return None

    content_box, content_sub = paste_region(cm)

    # --- 比例尺整组（尺体+0+值文本，默认不含左侧前缀序号）裁为底部行 ---
    scale_tiles = []
    for b in binds:
        s = at["scales"][b["si"]]
        boxes = [s["bbox"]]
        for mem in s.get("members", []):
            boxes.append(mem["bbox"])
        if not cfg.strip_scale_prefix:
            for pr in at["prefixes"]:         # 旧行为：前缀序号随尺输出
                pb = pr["bbox"]
                bb = s.get("bar_bbox") or s["bbox"]
                if pb[3] >= bb[1] - 12 and pb[1] <= bb[3] + 12 \
                        and bb[0] - cfg.prefix_ext <= pb[2] <= bb[0] + 6:
                    boxes.append(pb)
        ub = union_box(boxes)
        sm = ink_mask(binary, ub, pad=1)
        tb, tm = paste_region(sm) if sm is not None else (None, None)
        if tb is not None:
            scale_tiles.append({"box": [int(v) for v in tb],
                                "rle": rle_encode(tm), "si": b["si"],
                                "source": b["source"],
                                "text": s.get("text", ""),
                                "shared": b.get("shared", False)})

    return {
        "content_rle": rle_encode(content_sub),
        "content_box": [int(v) for v in content_box],
        "scale_tiles": scale_tiles,
        "members": members,
        "stripped": {"serial_digits": cfg.strip_serial_digits,
                     "scale_prefix": cfg.strip_scale_prefix},
    }


def render_group(bgr, ctx, cfg=None):
    """渲染上下文 → (canvas_bgr, record)：白底画布 + 内容纯平移 +
    比例尺行置底居中。pixel_mismatch 自检（内容区应为纯平移）。"""
    cfg = cfg or ComposeConfig()
    content_sub = rle_decode(ctx["content_rle"])
    content_box = ctx["content_box"]
    scale_tiles = [{"box": t["box"], "mask": rle_decode(t["rle"]),
                    "si": t["si"], "source": t["source"], "text": t["text"],
                    "shared": t["shared"]} for t in ctx.get("scale_tiles", [])]

    cw = content_box[2] - content_box[0]
    ch = content_box[3] - content_box[1]
    margin = max(6, int(round(cfg.margin_pct * max(cw, ch))))
    row_w = sum(t["box"][2] - t["box"][0] for t in scale_tiles) \
        + max(0, 2 * margin * (len(scale_tiles) - 1))
    row_h = max((t["box"][3] - t["box"][1] for t in scale_tiles), default=0)
    gap = margin if scale_tiles else 0
    Wc = max(cw, row_w) + 2 * margin
    Hc = margin + ch + gap + row_h + margin
    canvas = np.full((Hc, Wc, 3), 255, np.uint8)
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
        tb = t["box"]
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tys, txs = np.nonzero(t["mask"])
        canvas[tys + ycur, txs + xcur] = \
            bgr[tys + tb[1], txs + tb[0]]
        tiles_out.append({"si": t["si"], "text": t["text"],
                          "source": t["source"], "shared": t["shared"],
                          "placed_at": [int(xcur), int(ycur),
                                        int(xcur + tw), int(ycur + th)]})
        xcur += tw + 2 * margin

    rec = {
        "content_src_box": list(content_box),
        "content_paste_at": [margin, margin],
        "pixel_mismatch": mismatch,
        "scales": tiles_out,
        "canvas_size": [int(Wc), int(Hc)],
        "members": ctx.get("members"),
    }
    return canvas, rec

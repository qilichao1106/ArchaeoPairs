"""vision/compose 单测（E5：group_render_context + render_group）。

合成图构造组装上下文（与 assembly 测试同风格），验证：防串染剔除、
组内连接符并入、贴近说明文字并入、比例尺裁条、纯平移自检（pixel_mismatch=0）。
"""
from __future__ import annotations

import cv2
import numpy as np

from archaeopairs.vision import rle_decode
from archaeopairs.vision.compose import group_render_context, render_group


def _bgr_with_ink(size=(500, 500), ink_boxes=()):
    """白底 + 黑块合成图（bgr, binary）。"""
    bgr = np.full((size[1], size[0], 3), 255, np.uint8)
    for x0, y0, x1, y1 in ink_boxes:
        cv2.rectangle(bgr, (x0, y0), (x1, y1), (0, 0, 0), -1)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    binary = gray < 128
    return bgr, binary


def _view(vid, bbox, mask_boxes, **kw):
    """视图：bbox + 掩膜（bbox 内子块）。"""
    m = np.zeros((500, 500), bool)
    for x0, y0, x1, y1 in mask_boxes:
        m[y0:y1, x0:x1] = True
    v = {"id": vid, "bbox": list(bbox), "area": float(m.sum()),
         "contour": None, "mask": m, "label_nos": [], "label_ranks": [],
         "label_boxes": []}
    v.update(kw)
    return v


# ---------------------------------------------------------------------------
# group_render_context
# ---------------------------------------------------------------------------
def _crop_at(m, box, x, y):
    """全图坐标 → 内容裁片坐标索引（content_rle 是 paste_region 裁片）。"""
    return m[y - box[1], x - box[0]]


def test_ctx_content_and_anti_seepage():
    """组内容掩膜剔除其它组视图像素（防串染），序号数字默认剥离只记 bbox。"""
    bgr, binary = _bgr_with_ink(ink_boxes=[
        (50, 50, 150, 150),     # 组内视图 A
        (60, 60, 140, 140),     # 其它组视图 B：嵌套在 A 内（串染源）
        (90, 160, 105, 176),    # 序号 '1' 笔画（A 正下方）
    ])
    va = _view(0, (50, 50, 150, 150), [(50, 50, 150, 150)], label_nos=["1"],
               label_boxes=[[90, 160, 105, 176]])
    vb = _view(1, (60, 60, 140, 140), [(60, 60, 140, 140)])
    at = {"bgr": bgr, "binary": binary, "views": [va, vb],
          "labels": [], "prefixes": [], "links": [], "scales": [], "others": []}
    ctx = group_render_context(at, [0], [])
    assert ctx is not None
    m = rle_decode(ctx["content_rle"])
    box = ctx["content_box"]
    assert box == [50, 50, 150, 150]
    # B 的像素被剔除：content 掩膜不含 (100,100)（B 内部）
    assert not _crop_at(m, box, 100, 100)
    # A 边缘保留（(55,55) 属 A 不属 B）
    assert _crop_at(m, box, 55, 55)
    # 序号数字默认剥离：label 只记 bbox 不画（不进 content 掩膜）
    assert ctx["members"]["labels"] == [{"bbox": [90, 160, 105, 176],
                                         "painted": False}]
    assert ctx["stripped"]["serial_digits"] is True


def test_ctx_in_group_link_and_nearby_text():
    """组内连接符与贴近说明文字并入内容；远离图注不收。"""
    bgr, binary = _bgr_with_ink(ink_boxes=[
        (50, 50, 120, 120),     # 视图 A
        (50, 250, 120, 320),    # 视图 B（A 正下方，gap=130）
        (80, 130, 90, 240),     # 连接竖线（A/B 之间）
        (125, 50, 180, 66),     # 贴近说明文字（A 右侧 gap=5）
        (400, 400, 460, 416),   # 远处图注行（不收）
    ])
    va = _view(0, (50, 50, 120, 120), [(50, 50, 120, 120)])
    vb = _view(1, (50, 250, 120, 320), [(50, 250, 120, 320)])
    at = {"bgr": bgr, "binary": binary, "views": [va, vb],
          "labels": [], "prefixes": [],
          "links": [{"bbox": [80, 130, 90, 240], "reason": "connector",
                     "text": ""}],
          "scales": [],
          "others": [{"bbox": [125, 50, 180, 66], "reason": "text",
                      "text": "俯视"},
                     {"bbox": [400, 400, 460, 416], "reason": "text",
                      "text": "图注行"}]}
    ctx = group_render_context(at, [0, 1], [])
    m = rle_decode(ctx["content_rle"])
    box = ctx["content_box"]
    assert _crop_at(m, box, 85, 180)        # 连接竖线并入
    assert _crop_at(m, box, 150, 58)        # 贴近说明文字并入
    # 远处图注不收：内容 extent 不及图注行（y>=400）
    assert box[3] < 400 and box[2] < 400
    assert len(ctx["members"]["links"]) == 1
    assert ctx["members"]["texts"] == [{"bbox": [125, 50, 180, 66],
                                        "text": "俯视"}]


def test_ctx_scale_tile():
    """比例尺整组裁条：bbox+members 并集墨迹（默认不含前缀序号）。"""
    bgr, binary = _bgr_with_ink(ink_boxes=[
        (50, 50, 150, 150),                 # 视图
        (300, 440, 480, 446),               # 尺条
        (300, 420, 320, 436),               # 尺值文本成员
        (250, 420, 265, 436),               # 前缀序号（默认剥离）
    ])
    v = _view(0, (50, 50, 150, 150), [(50, 50, 150, 150)])
    at = {"bgr": bgr, "binary": binary, "views": [v],
          "labels": [], "prefixes": [{"bbox": [250, 420, 265, 436],
                                      "text": "1", "no": "1"}],
          "links": [],
          "scales": [{"bbox": [290, 410, 490, 460], "bar_bbox": [300, 440, 480, 446],
                      "text": "0—4厘米", "members": [{"bbox": [300, 420, 320, 436]}]}],
          "others": []}
    binds = [{"si": 0, "source": "L2_unique_shared", "prefix_nos": [],
              "shared": True}]
    ctx = group_render_context(at, [0], binds)
    assert len(ctx["scale_tiles"]) == 1
    tile = ctx["scale_tiles"][0]
    assert tile["si"] == 0 and tile["source"] == "L2_unique_shared"
    assert tile["text"] == "0—4厘米"
    tm = rle_decode(tile["rle"])
    # 尺条 + 值文本入裁条；前缀序号默认剥离（pad=1 内不含 250~265 段）
    assert tm.any()
    assert tm.shape[0] == tile["box"][3] - tile["box"][1]


def test_ctx_empty_group_returns_none():
    """组内无可画成员（视图无掩膜）→ None（S8 回退 mock 同形出图）。"""
    bgr, binary = _bgr_with_ink()
    v = _view(0, (50, 50, 150, 150), [])    # 空掩膜
    at = {"bgr": bgr, "binary": binary, "views": [v],
          "labels": [], "prefixes": [], "links": [], "scales": [], "others": []}
    assert group_render_context(at, [0], []) is None


# ---------------------------------------------------------------------------
# render_group
# ---------------------------------------------------------------------------
def test_render_group_pure_translation():
    """白底画布 + 内容纯平移：pixel_mismatch=0，边缘留白 margin>=6。"""
    ink = [(50, 50, 150, 150)]
    bgr, _binary = _bgr_with_ink(ink_boxes=ink)
    m = np.zeros((500, 500), bool)
    for x0, y0, x1, y1 in ink:
        m[y0:y1, x0:x1] = True
    from archaeopairs.vision import rle_encode
    from archaeopairs.vision.assembly import paste_region
    box, sub = paste_region(m)
    ctx = {"content_rle": rle_encode(sub), "content_box": [int(v) for v in box],
           "scale_tiles": [], "members": {}, "stripped": {}}
    canvas, rec = render_group(bgr, ctx)
    assert rec["pixel_mismatch"] == 0          # 纯平移逐像素一致
    assert rec["canvas_size"] == [100 + 2 * 6, 100 + 2 * 6]  # margin=max(6,3%*100)
    # 画布四角留白、中心为内容（黑）
    assert canvas[:3, :3].min() == 255
    assert canvas[50, 50].tolist() == [0, 0, 0]


def test_render_group_with_scale_row():
    """比例尺行置底水平居中；内容与尺行像素均来自源图纯平移。"""
    ink = [(50, 50, 150, 150)]
    scale_ink = [(300, 440, 480, 446)]
    bgr, _binary = _bgr_with_ink(ink_boxes=ink + scale_ink)
    from archaeopairs.vision import rle_encode
    from archaeopairs.vision.assembly import paste_region
    m = np.zeros((500, 500), bool)
    for x0, y0, x1, y1 in ink:
        m[y0:y1, x0:x1] = True
    cbox, csub = paste_region(m)
    sm = np.zeros((500, 500), bool)
    for x0, y0, x1, y1 in scale_ink:
        sm[y0:y1, x0:x1] = True
    sbox, ssub = paste_region(sm)
    ctx = {"content_rle": rle_encode(csub),
           "content_box": [int(v) for v in cbox],
           "scale_tiles": [{"box": [int(v) for v in sbox],
                            "rle": rle_encode(ssub), "si": 0,
                            "source": "L2_unique_shared", "text": "0—4厘米",
                            "shared": True}],
           "members": {}, "stripped": {}}
    canvas, rec = render_group(bgr, ctx)
    assert rec["pixel_mismatch"] == 0
    assert len(rec["scales"]) == 1
    # 画布高于纯内容（尺行 + gap）
    ch = cbox[3] - cbox[1]
    assert rec["canvas_size"][1] > ch + 2 * 6
    # 尺行置底：placed_at 在内容区之下
    assert rec["scales"][0]["placed_at"][1] >= 6 + ch

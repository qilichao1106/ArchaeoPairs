"""S6 真实组装路径（_run_real：vision/assembly E1–E4 全链 + state 写回）。

合成图 + 构造 vision_units（PaddleOCRReader units 同构）注入，VL 打桩
（三态可控），无 paddle/VL 依赖。mock 路径（vision_units 未置）由既有
149 项契约测试覆盖，此处只补分支选择断言。
"""
from __future__ import annotations

import cv2
import numpy as np

from archaeopairs.agents import s6
from archaeopairs.vision import extract_contours, rle_decode

# ---------------------------------------------------------------------------
# 合成图 + vision_units 构造
# ---------------------------------------------------------------------------
# 版面：左列器物视图（黑块）+ 其正下方序号 '1' 笔画；底部比例尺条
VIEW_RECT = (50, 100, 150, 300)      # 器物视图
LABEL_RECT = (90, 320, 105, 336)     # 序号 '1'（视图正下方 20px，rank0）
BAR_RECT = (300, 460, 480, 466)     # 比例尺条


def _make_image(tmp_path, name="img.png"):
    img = np.full((500, 500), 255, np.uint8)
    cv2.rectangle(img, VIEW_RECT[:2], VIEW_RECT[2:], 0, -1)
    cv2.rectangle(img, LABEL_RECT[:2], LABEL_RECT[2:], 0, -1)
    cv2.rectangle(img, BAR_RECT[:2], BAR_RECT[2:], 0, -1)
    p = tmp_path / name
    cv2.imwrite(str(p), img)
    return str(p)


def _make_units(img_path, n_scales=1):
    """合成图 -> (vision_units, scale_annotations, seq_annotations)。

    figures bbox 取自 extract_contours 实际输出（build_assembly 按 bbox
    精确命中轮廓索引取填充掩膜），与 PaddleOCRReader 真实行为同构。
    """
    bgr = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    kept, _removed, _bin = extract_contours(bgr, 5, 15.0)
    view_c = max(kept, key=lambda k: k["area"])           # 最大轮廓 = 器物视图
    scales = []
    for i in range(n_scales):
        scales.append({
            "kind": "bar", "bbox": [290, 440, 490, 480],
            "bar_bbox": list(BAR_RECT), "ticks": 4,
            "text": "0—4厘米", "raw_text": "0—4厘米", "value": 4.0,
            "unit": "厘米", "conf": 0.98, "verified": True,
            "members": [], "id": i})
    units = {
        "ok": True, "error": None, "backend": "stub",
        "image_size": [500, 500],
        "figures": [{"bbox": list(view_c["bbox"]),
                     "area": round(float(view_c["area"]), 1)}],
        "serials": [{"bbox": list(LABEL_RECT), "text": "1", "conf": 0.99,
                     "rotated": False, "no": "1", "scale_prefix": False}],
        "scales": scales,
        "texts": [], "others": [],
        "serial_set": {"nums": ["1"], "missing": [], "dups": [], "suspect": []},
        "stats": {"n_contours": len(kept), "n_figures": 1, "n_bars": n_scales,
                  "n_scales": n_scales, "n_serials": 1, "n_texts": 0,
                  "n_others": 0, "latency_s": 0.0},
        "contour_params": {"dilate_k": 5, "min_area": 15.0},
    }
    seq_annotations = [{"text": "1", "bbox": LABEL_RECT, "group": None}]
    scale_annotations = [
        {"text": "0—4厘米", "bbox": [290, 440, 490, 480], "unit": "厘米",
         "value": 4.0, "seq_ref": None} for _ in range(n_scales)]
    return units, seq_annotations, scale_annotations


def _real_state(tmp_path, n_scales=1):
    img = _make_image(tmp_path)
    units, seqs, scales = _make_units(img, n_scales=n_scales)
    return {
        "book_id": "synth", "figure_id": "fig1", "fileref": "img.png",
        "image_base": str(tmp_path), "caption": None, "figure_note": None,
        "trace_id": "t-real", "status": "RECOGNIZED",
        "note_items": [{"seq": "1", "seq_list": [1], "artifact_ids": ["M4:1"]}],
        "seq_annotations": seqs,
        "scale_annotations": scales,
        "vision_units": units,
    }


class _StubVl:
    """capability 协议 VL 桩：prefix 结果可控（三态），其余尽力返回 None。"""

    def __init__(self, prefix_result=(None, "unavailable"), strict=True):
        self.prefix_result = prefix_result
        self.strict = strict
        self.calls = []

    def judge_views(self, *, bgr, units, context="", **kw):
        self.calls.append(("judge", context))
        return [True] * len(units), "stub"

    def confirm_absorption(self, *, bgr, host_box, frag_box, **kw):
        return None, "stub"

    def read_serials(self, *, crops, context="", **kw):
        return [None] * len(crops), "stub"

    def same_artifact(self, *, bgr, box_a, box_b, **kw):
        return None, "stub"

    def read_scale_prefix(self, *, bgr, scale, where="", **kw):
        self.calls.append(("prefix", where))
        return self.prefix_result


# ---------------------------------------------------------------------------
# 真实路径：E2 绑定 + E3 单组 + E4 L2 共享 + 写回
# ---------------------------------------------------------------------------
def test_real_path_composed(services, tmp_path):
    """单视图+单尺：E2 rank0 绑 '1'，E4 L2 唯一共享，写回三件套。"""
    state = _real_state(tmp_path)
    out = s6.run(state, services)
    assert out["status"] == "COMPOSED"
    assert out["case_type"] == "rule_a"
    # 终态 atom_masks：每存活视图一个 MaskRecord
    assert len(out["atom_masks"]) == 1
    m = out["atom_masks"][0]
    assert m["seq_id"] == "1"
    assert m["scale_level"] == 2                  # L2_unique_shared
    assert m["incomplete"] is False
    mask = rle_decode(m["mask_rle"])
    assert mask.any() and int(mask.sum()) == m["area"]
    # view_groups：单组、掩膜索引连续、E4 绑定尺、E5 渲染上下文随组写回
    vg = out["view_groups"][0]
    assert vg["group_id"] == 0 and vg["mask_idxs"] == [0]
    assert vg["seq_ids"] == ["1"] and vg["scale_sis"] == [0]
    assert isinstance(vg["render"], dict)
    assert vg["render"]["content_rle"]
    assert [int(v) for v in vg["render"]["content_box"]] == vg["render"]["content_box"]
    # L2 唯一共享 → 比例尺整组裁条随组（底部行渲染素材）
    assert len(vg["render"]["scale_tiles"]) == 1
    assert vg["render"]["scale_tiles"][0]["si"] == 0
    # E4 绑定回填 seq_ref（组内唯一 seq）
    assert out["scale_annotations"][0]["seq_ref"] == "1"
    # VL 未注入（services 默认 None）→ 纯 CV，可见不阻断
    assert "vl_disabled" in out["fused"]["conflicts"]
    assert out["alarms"] == []


def test_real_path_note_missing_pending(services, tmp_path):
    """链①图注序号 '1' 但真实 E2 绑定失败场景由 E001 兜底：这里验证
    图注声明与 OCR 序号不一致时 E001 进 alarms → PENDING_REVIEW。"""
    state = _real_state(tmp_path)
    state["note_items"] = [{"seq": "2", "seq_list": [2], "artifact_ids": ["M4:2"]}]
    out = s6.run(state, services)
    assert "E001" in out["alarms"]          # 图注 '2' 图面无线图
    assert out["status"] == "PENDING_REVIEW"


def test_real_path_e004_e007_vl_unresolved(services, tmp_path):
    """双尺无前缀 + L3 VL 读不出（None）：E004 放弃 + vl_strict 下 E007。"""
    import dataclasses

    state = _real_state(tmp_path, n_scales=2)
    svc = dataclasses.replace(services, vl_arbiter=_StubVl())
    out = s6.run(state, svc)
    assert "E004" in out["alarms"]          # 两尺均放弃绑定
    assert "E007" in out["alarms"]          # 决定性门 None + strict=True
    assert out["status"] == "PENDING_REVIEW"
    assert any(c.startswith("scale_unbound:") for c in out["fused"]["conflicts"])
    # 组未绑任何比例尺 → 信息性冲突（不占 E 码）
    assert any(c.startswith("group_no_scale:") for c in out["fused"]["conflicts"])
    # scale_level=3（组无尺）；view_groups.scale_sis 为空
    assert out["atom_masks"][0]["scale_level"] == 3
    assert out["view_groups"][0]["scale_sis"] == []
    # L3 触达过 VL（每尺一次；另有 L1.5 前缀补救 2 次，均读不出）
    wheres = [c[1] for c in svc.vl_arbiter.calls if c[0] == "prefix"]
    assert wheres.count("L3") == 2
    assert wheres.count("scale_prefix") == 2


def test_real_path_vl_lenient_no_e007(services, tmp_path):
    """vl_strict=False：决定性门 None 只记 conflict，不报 E007。"""
    import dataclasses

    state = _real_state(tmp_path, n_scales=2)
    svc = dataclasses.replace(services, vl_arbiter=_StubVl(strict=False))
    out = s6.run(state, svc)
    assert "E007" not in out["alarms"]
    assert "E004" in out["alarms"]          # 放弃绑定仍硬报警


def test_real_path_vl_prefix_bind(services, tmp_path):
    """L3 VL 读出前缀 {1} → 尺绑到组（scale_level 1，seq_ref 回填）。"""
    import dataclasses

    state = _real_state(tmp_path, n_scales=2)
    svc = dataclasses.replace(
        services, vl_arbiter=_StubVl(prefix_result=([1], "vl read")))
    out = s6.run(state, svc)
    assert out["status"] == "COMPOSED"
    assert out["atom_masks"][0]["scale_level"] == 1          # VL 前缀硬绑
    # L1.5 前缀补救（多尺图）先于 L1：两尺均读到前缀 {1} → L1 双双硬绑该组
    assert out["scale_annotations"][0]["seq_ref"] == "1"
    assert out["scale_annotations"][1]["seq_ref"] == "1"
    assert out["view_groups"][0]["scale_sis"] == [0, 1]


def test_real_path_unreadable_image_pending(services, tmp_path):
    """图版像素不可读 → E1000 → 统一拦截 PENDING_REVIEW（graph 层语义）。"""
    from archaeopairs.errors import E1000ServiceUnavailableError

    state = _real_state(tmp_path)
    state["fileref"] = "nonexistent.png"
    try:
        s6.run(state, services)
    except E1000ServiceUnavailableError as e:
        assert e.service == "sam"
    else:  # pragma: no cover
        raise AssertionError("expected E1000ServiceUnavailableError")


# ---------------------------------------------------------------------------
# 分支选择：vision_units 未置 → mock 契约路径（无 view_groups 写回）
# ---------------------------------------------------------------------------
def test_mock_path_branch_no_view_groups(services, base_state):
    out = s6.run(dict(base_state), services)
    assert "view_groups" not in out
    assert "atom_masks" in out               # mock 路径仍产原子掩膜（空）

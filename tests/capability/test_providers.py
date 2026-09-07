"""capability/providers 真实 provider 契约（CvSegmenter/PaddleOCRReader）。

PaddleOCRReader 经 ArcheaRec(ocr=stub) 注入桩后端测试——无 paddle 依赖；
真 paddle 冒烟另设 importorskip 门控（首跑需下载 PP-OCRv6 权重）。
"""
from __future__ import annotations

import cv2
import numpy as np

from archaeopairs.vision import rle_decode

from archaeopairs.capability.providers import CvSegmenter, PaddleOCRReader


def _write_synth_png(tmp_path):
    """白底 + 两黑块 + 数字状笔触 → 临时 PNG（中文路径安全读取链路一并覆盖）。"""
    img = np.full((200, 300), 255, np.uint8)
    cv2.rectangle(img, (20, 10), (80, 60), 0, -1)
    cv2.rectangle(img, (150, 100), (250, 180), 0, -1)
    cv2.putText(img, "1", (100, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    p = tmp_path / "synth.png"
    cv2.imwrite(str(p), img)
    return str(p)


def test_cv_segmenter_mask_contract(tmp_path):
    seg = CvSegmenter(dilate_k=5, min_area=15.0)
    out = seg.segment(image_ref=_write_synth_png(tmp_path), prompts=[],
                      trace_id="t", figure_id="f", timeout=10.0, extra="ignored")
    assert len(out) >= 2  # 两实心块 + 数字笔画连通域
    for m in out:
        assert m["mask_rle"]
        assert len(m["bbox"]) == 4
        assert m["area"] > 0
        assert m["seq_id"] is None      # 绑定留给 S6
        assert m["incomplete"] is False
        # RLE 可解码回掩膜且非空
        mask = rle_decode(m["mask_rle"])
        assert mask.sum() == mask.astype(int).sum() > 0
    # 阅读序（bbox y 递增）
    ys = [m["bbox"][1] for m in out]
    assert ys == sorted(ys)


def test_cv_segmenter_unreadable_image():
    import pytest

    from archaeopairs.errors import E1000ServiceUnavailableError

    seg = CvSegmenter()
    with pytest.raises(E1000ServiceUnavailableError):
        seg.segment(image_ref="Z:/nonexistent/x.png", prompts=[], trace_id="t")


# ---------------------------------------------------------------------------
# PaddleOCRReader（ocr=stub 注入，无 paddle 依赖）
# ---------------------------------------------------------------------------
class _StubOcr:
    """ArcheaRec 可注入的最小 OCR 桩：name + recognize(crops)。"""

    name = "stub"

    def recognize(self, crops):
        return [("", 0.0)] * len(crops)


def _fake_rec():
    return {
        "ok": True, "error": None, "backend": "stub", "image_size": [300, 200],
        "scales": [{"kind": "bar", "bbox": [10, 150, 200, 20],
                    "bar_bbox": [10, 160, 200, 6], "ticks": 4,
                    "text": "0—4厘米", "raw_text": "0—4厘米", "value": 4.0,
                    "unit": "厘米", "conf": 0.98, "verified": True,
                    "members": [], "crop_base64": "AAAA", "contour_poly": [[1, 2]],
                    "id": 0}],
        "serials": [{"bbox": [20, 10, 30, 30], "text": "1", "conf": 0.99,
                     "rotated": False, "no": "1", "scale_prefix": False},
                    {"bbox": [40, 10, 50, 30], "text": "2", "conf": 0.99,
                     "rotated": False, "no": "2", "scale_prefix": True}],
        "texts": [], "figures": [], "others": [],
        "serial_set": {"nums": ["1", "2"], "missing": [], "dups": [],
                       "suspect": []},
        "stats": {"n_contours": 5, "n_figures": 0, "n_bars": 1, "n_scales": 1,
                  "n_serials": 2, "n_texts": 0, "n_others": 0, "latency_s": 0.1},
    }


def test_paddle_reader_mapping_and_trim(tmp_path, monkeypatch):
    """seqs/scales 契约映射 + scale_prefix 序号隔离 + units 剥离 base64/poly。"""
    reader = PaddleOCRReader(ocr=_StubOcr())
    monkeypatch.setattr(reader._rec, "recognize",
                        lambda image, kept=None: _fake_rec())
    resp = reader.read(image_ref=_write_synth_png(tmp_path), regions=[],
                       trace_id="t", figure_id="f", timeout=10.0, extra="ignored")
    # 正文序号进 seqs，比例尺前缀序号隔离（serial_set 只计正文序号）
    assert [s["text"] for s in resp["seqs"]] == ["1"]
    assert tuple(resp["seqs"][0]["bbox"]) == (20, 10, 30, 30)
    # 比例尺映射 ScaleAnnotation 字段
    sc = resp["scales"][0]
    assert sc["text"] == "0—4厘米" and sc["value"] == 4.0 and sc["unit"] == "厘米"
    assert sc["seq_ref"] is None
    assert resp["orientation"] == "h"
    # units：前缀序号保留 + base64/contour_poly 剥离（checkpoint 体积）
    units = resp["units"]
    assert len(units["serials"]) == 2          # 前缀序号保留给 S6 E4 L1
    assert "crop_base64" not in units["scales"][0]
    assert "contour_poly" not in units["scales"][0]
    assert units["serial_set"]["nums"] == ["1", "2"]


def test_paddle_reader_blank_image(tmp_path):
    """无轮廓空白图：非失败，产空结果 + 空 units 骨架。"""
    img = np.full((100, 100), 255, np.uint8)
    p = tmp_path / "blank.png"
    cv2.imwrite(str(p), img)
    reader = PaddleOCRReader(ocr=_StubOcr())
    resp = reader.read(image_ref=str(p), regions=[], trace_id="t")
    assert resp["seqs"] == [] and resp["scales"] == []
    assert resp["units"]["ok"] is True
    assert resp["units"]["stats"]["n_contours"] == 0
    assert resp["units"]["serial_set"]["nums"] == []


def test_paddle_reader_unreadable_image():
    import pytest

    from archaeopairs.errors import E400OcrAllFailError

    reader = PaddleOCRReader(ocr=_StubOcr())
    with pytest.raises(E400OcrAllFailError):
        reader.read(image_ref="Z:/nonexistent/x.png", regions=[], trace_id="t")


def test_paddle_reader_real_paddle_smoke(tmp_path):
    """真 paddle 冒烟（门控）：合成数字图能走完 recognize 全链路。

    首跑下载 PP-OCRv6 权重需网络；不校验读值正确性（合成位图字体
    与训练分布有差异），只验证契约结构完整。
    """
    import pytest

    pytest.importorskip("paddleocr")
    img = np.full((160, 320), 255, np.uint8)
    for i, ch in enumerate("123"):
        cv2.putText(img, ch, (40 + i * 90, 90), cv2.FONT_HERSHEY_SIMPLEX,
                    2.0, 0, 4)
    cv2.rectangle(img, (40, 130), (240, 134), 0, -1)   # 比例尺条
    p = tmp_path / "digits.png"
    cv2.imwrite(str(p), img)
    reader = PaddleOCRReader()
    resp = reader.read(image_ref=str(p), regions=[], trace_id="t")
    assert set(resp) >= {"seqs", "scales", "orientation", "units"}
    assert resp["units"]["ok"] is True
    assert resp["units"]["backend"] == "paddle"


# ---------------------------------------------------------------------------
# VlArbiterService（底层 VlArbiter 打桩，不发真实请求）
# ---------------------------------------------------------------------------
class _StubArb:
    """vision.vl.VlArbiter 桩：记录调用并返回可辨别的三态结果。"""

    def __init__(self, enabled=True, preset=None, config=None, **kw):
        self.calls = []

    def judge_view_candidates_v2(self, bgr, units, context=""):
        self.calls.append(("judge", context))
        return [True, None], "note"

    def confirm_absorption(self, bgr, host_box, frag_box):
        self.calls.append(("absorb",))
        return False, "reason"

    def read_serial_crops(self, crops, context=""):
        self.calls.append(("serial", context))
        return ["1", ""], "note"

    def same_artifact(self, bgr, box_a, box_b):
        self.calls.append(("same",))
        return True, "same"

    def read_scale_prefix(self, bgr, scale, where="scale_prefix"):
        self.calls.append(("prefix", where))
        return [1, 2], "nums"

    def stats(self):
        return {"n_records": len(self.calls)}


def _make_vl_service(monkeypatch):
    import archaeopairs.vision.vl as vl_mod

    monkeypatch.setattr(vl_mod, "VlArbiter", _StubArb)
    from archaeopairs.capability.providers import VlArbiterService

    return VlArbiterService(preset="glm-53-flash", cache_dir="runs/vl_cache",
                            strict=True)


def test_vl_service_facade_delegation(monkeypatch):
    """协议方法映射到 VlArbiter 5 任务入口；网关注入 kwargs 全部吞下。"""
    import numpy as np

    svc = _make_vl_service(monkeypatch)
    bgr = np.full((10, 10, 3), 255, np.uint8)
    flags, note = svc.judge_views(bgr=bgr, units=[{"bbox": [0, 0, 5, 5]}] * 2,
                                  context="e1.5", trace_id="t", figure_id="f",
                                  timeout=60.0, operation="vl_review")
    assert flags == [True, None]
    is_frag, _ = svc.confirm_absorption(bgr=bgr, host_box=[0, 0, 5, 5],
                                        frag_box=[1, 1, 4, 4], trace_id="t",
                                        figure_id="f", timeout=60.0)
    assert is_frag is False
    reads, _ = svc.read_serials(crops=[], context="e2.5", trace_id="t",
                                figure_id="f", timeout=60.0)
    assert reads == ["1", ""]
    same, _ = svc.same_artifact(bgr=bgr, box_a=[0, 0, 5, 5], box_b=[5, 5, 9, 9],
                                trace_id="t", figure_id="f", timeout=60.0)
    assert same is True
    nums, _ = svc.read_scale_prefix(bgr=bgr, scale={"bbox": [0, 0, 5, 5]},
                                    where="L3", trace_id="t", figure_id="f",
                                    timeout=60.0)
    assert nums == [1, 2]
    # 5 个任务入口全部触达
    assert len(svc.arbiter.calls) == 5


def test_vl_service_strict_popped(monkeypatch):
    """vl_config 的 strict 是 S6 报警策略开关，不透传底层 VlArbiter。"""
    svc = _make_vl_service(monkeypatch)
    assert svc.strict is True
    assert isinstance(svc.arbiter, _StubArb)
    assert isinstance(svc.stats(), dict)

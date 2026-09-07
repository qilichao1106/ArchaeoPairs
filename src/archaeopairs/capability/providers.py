"""真实能力 provider（自 legacy/extract/ 原型迁移的视觉链路适配层）。

CvSegmenter —— SAM 协议槽位的本地实现：OpenCV 轮廓掩膜（无远程模型）。
PaddleOCRReader —— OCR 协议实现：vision/rec.ArchaeaRec（PP-OCRv6 本地）。
VlArbiterService —— VL 三态仲裁门面：vision/vl.VlArbiter（OpenAI 兼容远程）。

协议适配约定：网关（gateway.call）会注入 figure_id/timeout kwargs（gateway.py），
真实 provider 必须如 mock 一样以 **kw 吞下（tests/test_hard_constraints 的
monkeypatch 也依赖该签名契约）。VL 实现永不 raise（三态契约，None=悬而未决），
网关仅作遥测/限流包装，重试惰性。
"""
from __future__ import annotations

import cv2

from ..errors import E1000ServiceUnavailableError, E400OcrAllFailError
from ..state import ScaleAnnotation, SeqAnnotation
from ..vision import extract_contours, filled_mask, load_image, rle_encode


class CvSegmenter:
    """本地轮廓分割（SAM 协议槽位；远程 SAM 已按决策移除）。

    extract_contours（OTSU+膨胀+轮廓+孔洞剔除）→ 逐轮廓 filled_mask 掩膜。
    所有保留轮廓均成为原子（器物体/数字笔画/比例尺条/连接线——S5/S6 需要
    全部组件，S6 真实路径再重写为终态视图掩膜）。
    本地模式 incomplete 恒 False（共享基准线检测未实现；E006 仍为上游注入语义）。
    """

    def __init__(self, dilate_k: int = 5, min_area: float = 15.0):
        self.dilate_k = dilate_k
        self.min_area = min_area

    def segment(self, *, image_ref: str, prompts: list[dict], trace_id: str,
                figure_id: str = "", timeout: float | None = None, **kw) -> list[dict]:
        try:
            bgr, _ = load_image(image_ref)  # 中文路径安全
        except OSError as e:
            raise E1000ServiceUnavailableError(
                f"cv segment: 图片不可读 {image_ref} ({e})", service="sam") from e
        if bgr is None:
            raise E1000ServiceUnavailableError(
                f"cv segment: 图片解码失败 {image_ref}", service="sam")
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        kept, _removed, _bin = extract_contours(gray, self.dilate_k, self.min_area)
        out = []
        for item in kept:
            mask = filled_mask(item["contour"], gray.shape)
            out.append({
                "mask_rle": rle_encode(mask.astype(bool)),
                "bbox": tuple(int(v) for v in item["bbox"]),
                "area": int(round(item["area"])),
                "seq_id": None,       # 绑定留给 S6（E2）
                "incomplete": False,
            })
        return out


def _trim_units(rec: dict) -> dict:
    """识别结果 -> S6 可 checkpoint 化的 units（剥离 base64 裁片与轮廓多边形）。

    S6 真实路径按 bbox 从重算的轮廓掩膜取像素，不依赖 RLE/多边形；
    base64 裁片（数十 KB/条）会撑爆 checkpoint，故剥离。
    """
    out: dict = {}
    for k, v in rec.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out[k] = [{kk: vv for kk, vv in e.items()
                       if kk not in ("crop_base64", "contour_poly")} for e in v]
        else:
            out[k] = v
    return out


class PaddleOCRReader:
    """本地 PaddleOCR 识别（archea_rec 迁移；PP-OCRv6，无回退后端）。

    read() 内部重跑 extract_contours（毫秒级）再 ArcheaRec.recognize：
    免把轮廓序列化进 S4→S5 checkpoint，且与原型 build_atoms 同构。
    返回 mock 同形契约 {"seqs","scales","orientation"}，另附 "units"
    （_trim 后的完整识别结果）经 s5 透传 state.vision_units 供 S6 组装。
    比例尺前缀序号（scale_prefix）不进 seqs（序号集合校验只计正文序号），
    但保留在 units.serials 中供 S6 E4 L1 前缀硬匹配。
    """

    def __init__(self, **rec_kwargs):
        from ..vision.rec import ArcheaRec

        self._rec = ArcheaRec(**rec_kwargs)   # OcrBackend 初始化失败即报警

    def read(self, *, image_ref: str, regions: list[dict], trace_id: str,
             figure_id: str = "", timeout: float | None = None,
             operation: str = "read", **kw) -> dict:
        try:
            bgr, _ = load_image(image_ref)  # 中文路径安全
        except OSError as e:
            raise E400OcrAllFailError(
                f"paddle ocr: 图片不可读 {image_ref} ({e})") from e
        if bgr is None:
            raise E400OcrAllFailError(f"paddle ocr: 图片解码失败 {image_ref}")
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        kept, _removed, _bin = extract_contours(
            gray, self._rec.p["dilate_k"], self._rec.p["min_area"])
        if kept:
            rec = self._rec.recognize(bgr, kept)
            if not rec.get("ok"):
                raise E400OcrAllFailError(
                    f"paddle ocr: 识别失败 {rec.get('error')}")
        else:                               # 空白图：无轮廓非失败，产空结果
            from ..vision.rec import check_serial_set

            rec = {"ok": True, "error": None, "backend": self._rec.ocr.name,
                   "image_size": [gray.shape[1], gray.shape[0]],
                   "scales": [], "serials": [], "texts": [], "figures": [],
                   "others": [], "serial_set": check_serial_set([]),
                   "stats": {"n_contours": 0, "n_figures": 0, "n_bars": 0,
                             "n_scales": 0, "n_serials": 0, "n_texts": 0,
                             "n_others": 0, "latency_s": 0.0}}
        seqs = [
            SeqAnnotation(text=str(s.get("no") or s.get("text", "")),
                          bbox=tuple(int(v) for v in s["bbox"])).model_dump()
            for s in rec["serials"] if not s.get("scale_prefix")
        ]
        scales = [
            ScaleAnnotation(text=str(s.get("text", "")),
                            bbox=tuple(int(v) for v in s["bbox"]),
                            unit=str(s.get("unit") or "cm"),
                            value=s.get("value"), seq_ref=None).model_dump()
            for s in rec["scales"]
        ]
        units = _trim_units(rec)
        # 轮廓参数随行：S6 真实路径须以同参重跑 extract_contours，识别
        # bbox 才能与轮廓索引对齐（build_assembly 按 bbox 精确匹配取掩膜）
        units["contour_params"] = {"dilate_k": self._rec.p["dilate_k"],
                                   "min_area": self._rec.p["min_area"]}
        return {"seqs": seqs, "scales": scales, "orientation": "h",
                "units": units}


class VlArbiterService:
    """VL 三态仲裁门面（capability/base.VLArbiter 协议实现）。

    持有 vision/vl.VlArbiter 实例，把协议方法映射到 5 个任务入口
    （E1.5 vl_review / E1.R2 absorb_check / E2.5 read_serial /
    E3 same_artifact / E4 L3 read_prefix）。三态契约（True/False/None）
    由底层 VlArbiter 保证；本层只做签名适配，不吞判定。

    vl_config 中的 "strict" 是 S6 报警策略开关（None 决定性门是否报 E007），
    非 VlArbiter 参数，在此弹出并暴露为属性。超时由 VLConfig.timeout
    自治（含内部重试），网关注入的 timeout 不覆盖。
    """

    def __init__(self, **vl_kwargs):
        from ..vision.vl import VlArbiter

        self.strict = bool(vl_kwargs.pop("strict", True))
        self._arb = VlArbiter(enabled=True, **vl_kwargs)

    @property
    def arbiter(self):
        """底层 VlArbiter（records/stats/dump_records 调试接口）。"""
        return self._arb

    def stats(self) -> dict:
        return self._arb.stats()

    # -- E1.5 视图仲裁（judge_view_candidates_v2）----------------------
    def judge_views(self, *, bgr, units, context: str = "", trace_id: str = "",
                    figure_id: str = "", timeout: float | None = None,
                    **kw) -> tuple:
        return self._arb.judge_view_candidates_v2(bgr, units, context=context)

    # -- E1.R2 碎片吸收确认 ---------------------------------------------
    def confirm_absorption(self, *, bgr, host_box, frag_box, trace_id: str = "",
                           figure_id: str = "", timeout: float | None = None,
                           **kw) -> tuple:
        return self._arb.confirm_absorption(bgr, host_box, frag_box)

    # -- E2.5 序号漏读抢救 ----------------------------------------------
    def read_serials(self, *, crops, context: str = "", trace_id: str = "",
                     figure_id: str = "", timeout: float | None = None,
                     **kw) -> tuple:
        return self._arb.read_serial_crops(crops, context=context)

    # -- E3 视图分组仲裁 -------------------------------------------------
    def same_artifact(self, *, bgr, box_a, box_b, trace_id: str = "",
                      figure_id: str = "", timeout: float | None = None,
                      **kw) -> tuple:
        return self._arb.same_artifact(bgr, box_a, box_b)

    # -- E4 L3 比例尺前缀读取 --------------------------------------------
    def read_scale_prefix(self, *, bgr, scale, where: str = "",
                          trace_id: str = "", figure_id: str = "",
                          timeout: float | None = None, **kw) -> tuple:
        return self._arb.read_scale_prefix(bgr, scale, where=where)

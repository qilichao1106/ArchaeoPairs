"""S5 识别器（§4.5）。Node: 链③标注识别（序号/比例尺/说明文字/连接符）。

对 S4 原子掩膜与像素区域执行识别（P0：OCR 能力接口），输出链③标注：
图片内数字序号、比例尺组（尺体+起点0+值文本）、说明文字；serial_set
集合校验（连续性/重复检测）供 S6 绑定校验。纯识别节点：不做三链仲裁
（仲裁职责自 V0.5.4 并入 S6，§4.6.3）。

VL 读号兜底（§4.5）：OCR 低置信/漏读时调用 VL 读号（read_serial_crops /
read_scale_prefix），三态判定（True/False/None）；P0 mock 链路 OCR 覆盖
ground 序号，生产实现接入 VLM 读号后启用兜底分支。

V0.5.4：OCR 识别职责自原 S4 移至 S5（E400/E401 归属 S5）。
"""
from __future__ import annotations

from . import Services


def _serial_set_check(seq_annotations: list[dict]) -> list[str]:
    """serial_set 集合校验（§4.5.1）：连续性/重复检测，异常项供 S6 绑定校验。"""
    anomalies: list[str] = []
    serials: list[str] = []
    for ann in seq_annotations:
        text = str(ann.get("text", "")).strip()
        if text.isdigit():
            serials.append(text)
    seen: set[str] = set()
    for s in serials:
        if s in seen and f"duplicate_serial:{s}" not in anomalies:
            anomalies.append(f"duplicate_serial:{s}")
        seen.add(s)
    nums = sorted(int(s) for s in seen if s.isdigit())
    if len(nums) >= 2 and nums == list(range(nums[0], nums[0] + len(nums))):
        pass  # 连续序号：正常
    elif len(nums) >= 2:
        anomalies.append(f"non_contiguous_serials:{nums[0]}..{nums[-1]}")
    return anomalies


def run(state: dict, svc: Services) -> dict:
    resp = svc.gateway.call(
        "ocr", svc.ocr.read, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=state["fileref"], regions=[],
        operation="read",
    )
    seq_annotations = resp["seqs"]
    scale_annotations = resp["scales"]
    # 方向判定回填：S4 默认 'h'，S5 识别文字方向后可修正（§4.4.2 多向 → 旋转统一）
    out: dict = {
        "seq_annotations": seq_annotations,
        "scale_annotations": scale_annotations,
        "serial_anomalies": _serial_set_check(seq_annotations),
        "status": "RECOGNIZED",
    }
    if resp.get("orientation"):
        out["orientation"] = resp["orientation"]
    # VL 读号兜底（§4.5）：OCR 低置信/漏读时三态判定；P0 mock 不触发，
    # 生产实现接 read_serial_crops / read_scale_prefix，None（证据不足）交 S6 保守处置。
    return out

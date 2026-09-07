"""S5 识别器（§4.5）。Node: 链③标注识别（序号/比例尺/说明文字/连接符）。

对 S4 原子掩膜与像素区域执行识别（P0：OCR 能力接口），输出链③标注：
图片内数字序号、比例尺组（尺体+起点0+值文本）、说明文字；serial_set
集合校验（连续性/重复检测）供 S6 绑定校验。纯识别节点：不做三链仲裁
（仲裁职责自 V0.5.4 并入 S6，§4.6.3）。

VL 读号兜底（§4.5）：OCR 低置信/漏读时调用 VL 读号（read_serial /
read_prefix），三态判定（True/False/None）；P0 mock 链路 OCR 覆盖
ground 序号，生产实现的读号兜底在 S6 E2.5（需视图几何上下文）执行。

V0.5.4：OCR 识别职责自原 S4 移至 S5（E400/E401 归属 S5）。
V0.5.6：serial_set 校验统一入口 vision.rec.check_serial_set——删除本地
简化版 _serial_set_check（双实现反模式：完整版结果曾闲置在
units.serial_set 而弱版独占进 conflicts）。真实路径直接复用
PaddleOCRReader 透传的 units.serial_set（ArcheaRec.recognize 内已算，
免二次计算）；mock 路径按 seq_annotations 回退调用同一函数。异常项
格式化为 conflicts 字符串列表（duplicate/missing/suspect_serial:N）供
S6 _arbitrate 消费，list[str] 契约形状不变。
"""
from __future__ import annotations

from pathlib import Path

from ..vision.rec import check_serial_set
from . import Services


def _resolve_image(state: dict) -> str:
    """图版像素绝对路径（与 S4 同模式：image_base/fileref 拼接）。

    真实 provider（PaddleOCRReader）须绝对路径读像素；mock 对取值无感。
    """
    image_ref = state["fileref"]
    if state.get("image_base"):
        _p = Path(state["image_base"]) / state["fileref"]
        if _p.is_file():
            image_ref = str(_p)
    return image_ref


def _serial_anomalies(sset: dict) -> list[str]:
    """check_serial_set 输出字典 → conflicts 字符串列表（S6 _arbitrate 消费）。

    dups → duplicate_serial:N；missing → missing_serial:N（1..max 缺号，
    严于旧版 non_contiguous 的"min 起连续"判定）；suspect → suspect_serial:N
    （离群大号，n > 2*median+2）。保持 list[str] 契约形状，S6 侧
    f"serial_check:{a}" 前缀逻辑不变。
    """
    out: list[str] = []
    for d in sset.get("dups") or []:
        out.append(f"duplicate_serial:{d}")
    for m in sset.get("missing") or []:
        out.append(f"missing_serial:{m}")
    for s in sset.get("suspect") or []:
        out.append(f"suspect_serial:{s}")
    return out


def run(state: dict, svc: Services) -> dict:
    resp = svc.gateway.call(
        "ocr", svc.ocr.read, figure_id=state["figure_id"], trace_id=state["trace_id"],
        image_ref=_resolve_image(state), regions=[],
        operation="read",
    )
    seq_annotations = resp["seqs"]
    scale_annotations = resp["scales"]
    units = resp.get("units")
    # serial_set 统一入口（V0.5.6）：真实路径复用 ArcheaRec.recognize 已算
    # 结果（units.serial_set，_trim_units 保留所有 key），免二次计算；mock
    # 路径（units=None）按 seq_annotations 回退调用同一 check_serial_set。
    if units is not None and units.get("serial_set") is not None:
        sset = units["serial_set"]
    else:
        sset = check_serial_set(
            [str(a.get("text", "")).strip() for a in seq_annotations])
    # 方向判定回填：S4 默认 'h'，S5 识别文字方向后可修正（§4.4.2 多向 → 旋转统一）
    out: dict = {
        "seq_annotations": seq_annotations,
        "scale_annotations": scale_annotations,
        "serial_anomalies": _serial_anomalies(sset),
        "status": "RECOGNIZED",
    }
    if resp.get("orientation"):
        out["orientation"] = resp["orientation"]
    # 真实 OCR（PaddleOCRReader）附带完整识别结果 units（已剥离 base64）：
    # 透传 state.vision_units，S6 据此走真实组装路径；mock 链路不携带（None），
    # S6 维持现有契约实现。VL 读号兜底在 S6 E2.5（需视图几何）。
    if units is not None:
        out["vision_units"] = units
    return out

"""视觉子包：本地 CV 算法（分割/识别/组装/成图/VL 仲裁）。

自 legacy/extract/ 原型迁移（V0.5.4 后真实链路）；纯算法层，
不感知 LangGraph State 与能力网关——由 capability/providers.py 适配。
"""
from .assembly import (
    AssemblyConfig,
    bind_labels,
    bind_scales,
    build_assembly,
    group_views,
    ink_mask,
    rescue_missing_serials,
    vl_review,
)
from .compose import ComposeConfig, group_render_context, render_group
from .images import decode_image_bytes, load_image, png_base64
from .rle import rle_decode, rle_encode
from .seg import (
    contour_poly,
    contour_to_points,
    extract_contours,
    filled_mask,
    mask_iou,
    merge_overlapping_instances,
)
from .vl import PRESETS, VLConfig, VlArbiter, load_config

__all__ = [
    "decode_image_bytes", "load_image", "png_base64",
    "rle_encode", "rle_decode",
    "extract_contours", "contour_to_points", "filled_mask", "mask_iou",
    "contour_poly", "merge_overlapping_instances",
    "PRESETS", "VLConfig", "VlArbiter", "load_config",
    "AssemblyConfig", "build_assembly", "vl_review", "bind_labels",
    "rescue_missing_serials", "group_views", "bind_scales", "ink_mask",
    "ComposeConfig", "group_render_context", "render_group",
]

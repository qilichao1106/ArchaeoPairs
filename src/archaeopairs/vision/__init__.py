"""Pixel-level view segmentation and COCO-style RLE (T-006)."""

from archaeopairs.models import View
from archaeopairs.vision.rle import rle_decode, rle_encode
from archaeopairs.vision.seg import (
    extract_contours,
    filled_mask,
    load_image,
    mask_iou,
    segment_views,
)

__all__ = [
    "View",
    "extract_contours",
    "filled_mask",
    "load_image",
    "mask_iou",
    "rle_decode",
    "rle_encode",
    "segment_views",
]

"""OpenCV contour segmentation producing pixel-level views (T-006).

Each kept contour becomes one :class:`archaeopairs.models.View`: its mask is
filled from the contour itself (never a bbox rectangle), encoded as RLE over
the full image, and numbered in reading order (top-to-bottom, left-to-right).
No bbox cutting and no pixel inpainting happen here.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from archaeopairs.models import View
from archaeopairs.vision.rle import rle_encode


def load_image(path) -> np.ndarray:
    """Read an image as BGR via ``np.fromfile`` + ``cv2.imdecode``.

    This keeps Windows paths with Chinese characters / spaces working, unlike
    ``cv2.imread``.  Unreadable or non-image files raise ``OSError``.
    """
    source = Path(path)
    try:
        buffer = np.fromfile(str(source), dtype=np.uint8)
    except OSError as exc:
        raise OSError(f"cannot read image file: {source}") from exc
    if buffer.size == 0:
        raise OSError(f"image file is empty: {source}")
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise OSError(f"cannot decode image: {source}")
    return image


def _as_gray(gray) -> np.ndarray:
    array = np.asarray(gray)
    if array.ndim == 3:
        if array.shape[2] == 4:
            array = cv2.cvtColor(array, cv2.COLOR_BGRA2GRAY)
        else:
            array = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    if array.ndim != 2:
        raise ValueError(f"gray image must be 2-D, got shape {array.shape}")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return array


def _bbox(contour: np.ndarray) -> tuple[int, int, int, int]:
    x, y, width, height = cv2.boundingRect(contour)
    return int(x), int(y), int(x) + int(width), int(y) + int(height)


def _contains(outer: np.ndarray, inner: np.ndarray) -> bool:
    """True when every ``inner`` vertex lies inside/on the ``outer`` polygon."""
    return all(cv2.pointPolygonTest(outer, (float(px), float(py)), False) >= 0
               for px, py in inner.reshape(-1, 2))


def _reading_key(item: dict) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = item["bbox"]
    return y0, x0, y1, x1


def _raw_ink(binary: np.ndarray, min_area: float) -> np.ndarray:
    """Ink mask restricted to raw connected components of area >= ``min_area``."""
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    ink = binary.copy()
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= min_area:
            continue
        ink[labels == label] = 0
    return ink


def _masked_ink(contour: np.ndarray, ink: np.ndarray) -> int:
    """Count raw ink pixels lying inside ``contour`` (same image coordinates)."""
    local = np.zeros(ink.shape, dtype=np.uint8)
    cv2.drawContours(local, [contour], -1, 255, thickness=cv2.FILLED)
    return int(np.count_nonzero(local.astype(np.bool_) & ink.astype(np.bool_)))

def extract_contours(gray, dilate_k: int = 5, min_area: float = 15.0):
    """Find line-drawing contours via OTSU + dilation + ``RETR_CCOMP``.

    The OTSU binary is inverted (ink -> 255).  Raw ink connected components
    smaller than ``min_area`` are dropped first (so a few-pixel speck cannot
    be inflated by the closing step); the remaining ink is dilated with a
    ``dilate_k`` ellipse (closing dotted/anti-aliased strokes into one
    component), contours are found with ``RETR_CCOMP`` and each bbox is
    expanded by the dilation radius.

    Holes (child contours of a parent in the CCOMP hierarchy) and contours
    whose every vertex falls inside a larger contour go to ``removed``.
    ``kept``/``removed`` hold ``{"bbox", "area", "contour", "hole"}`` dicts
    in reading order; ``area`` is the raw ink pixel count inside the contour
    and ``bbox`` is ``(x0, y0, x1, y1)`` (right/bottom exclusive).  ``binary``
    is the inverted OTSU image (uint8, 0/255) before filtering/dilation.
    """
    source = _as_gray(gray)
    _threshold, binary = cv2.threshold(
        source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    ink = _raw_ink(binary, float(min_area))
    kernel_size = max(1, int(dilate_k))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    dilated = cv2.dilate(ink, kernel)
    contours, hierarchy = cv2.findContours(
        dilated, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is None:
        contours, hierarchy = [], np.empty((1, 4), dtype=np.int32)
    hierarchy = hierarchy.reshape(-1, 4)
    pad = kernel_size // 2
    height, width = binary.shape

    items: list[dict] = []
    for index, contour in enumerate(contours):
        x0, y0, x1, y1 = _bbox(contour)
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(width, x1 + pad), min(height, y1 + pad)
        items.append({
            "bbox": (x0, y0, x1, y1),
            "area": _masked_ink(contour, ink),
            "contour": contour,
            "hole": int(hierarchy[index][3]) >= 0,
            "index": index,
        })

    kept: list[dict] = []
    removed: list[dict] = []
    for item in sorted(items, key=_reading_key):
        enclosing = any(
            other["index"] != item["index"]
            and other["index"] in (hierarchy[item["index"]][3],
                                   hierarchy[other["index"]][3])
            and _contains(other["contour"], item["contour"])
            for other in items
        )
        if item["area"] < float(min_area) or item["hole"] or enclosing:
            target, hole = removed, item["hole"] or enclosing
            target.append({"bbox": item["bbox"], "area": item["area"],
                           "contour": item["contour"], "hole": bool(hole)})
        else:
            kept.append({"bbox": item["bbox"], "area": item["area"],
                         "contour": item["contour"], "hole": False})
    return kept, removed, binary

def filled_mask(contour, shape) -> np.ndarray:
    """Rasterize ``contour`` into a filled boolean mask of ``shape`` (h, w)."""
    height, width = (int(n) for n in shape)
    mask = np.zeros((height, width), dtype=np.uint8)
    points = np.asarray(contour)
    if points.size == 0:
        raise ValueError("contour has no points")
    if points.dtype != np.int32:
        points = np.rint(points).astype(np.int32)
    cv2.drawContours(mask, [points.reshape(-1, 1, 2).astype(np.int32)],
                     -1, 255, thickness=cv2.FILLED)
    return mask.astype(np.bool_)


def mask_iou(a, b) -> float:
    """Intersection-over-union of two boolean masks (``0.0`` when both empty)."""
    first = np.asarray(a, dtype=np.bool_)
    second = np.asarray(b, dtype=np.bool_)
    if first.shape != second.shape:
        raise ValueError(f"mask shapes differ: {first.shape} vs {second.shape}")
    union = int(np.count_nonzero(first | second))
    if union == 0:
        return 0.0
    return float(np.count_nonzero(first & second)) / float(union)


def segment_views(image_path, *, dilate_k: int = 5,
                  min_area: float = 15.0) -> list[View]:
    """Segment an image into pixel-level :class:`View` objects.

    Each view gets its contour-filled mask (RLE over the full image), the
    contour bbox and pixel count.  ``view_id`` follows reading order.
    A blank/white image yields ``[]``.  Masks keep only pixels inside the
    view's own contour: no bbox rectangles, no pixel completion.
    """
    image = load_image(image_path)
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    kept, _removed, _binary = extract_contours(
        gray, dilate_k=dilate_k, min_area=min_area
    )
    views: list[View] = []
    for view_id, item in enumerate(kept):
        mask = filled_mask(item["contour"], (height, width))
        x0, y0, x1, y1 = item["bbox"]
        views.append(View(view_id=view_id, bbox=(x0, y0, x1, y1),
                          area=int(np.count_nonzero(mask)),
                          mask_rle=rle_encode(mask), incomplete=False))
    return views

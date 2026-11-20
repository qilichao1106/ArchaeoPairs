"""White-background composition of one ArtifactUnit (R-IMG-01..10, AC-05).

The content area is a *pure translation* of the original pixels: the tight
bbox of the unit's union mask is copied verbatim (no scaling, rotation,
reordering or denoising) onto a white canvas with ``max(min_margin,
round(margin_pct * max(cw, ch)))`` pixels of padding.  A per-pixel check
re-reads the pasted area and reports ``pixel_mismatch`` (must be 0).

Bound scale bars are cropped from the original image by their own bbox and
laid in binding order on one row under the content, centred.  A shared bar is
emitted once per binding entry; a ``scale_id`` missing from ``scales`` is
listed in ``meta["missing_scales"]`` instead of crashing.  A unit with no
bindings is allowed (the caller marks ``no_scale``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from archaeopairs.models import ArtifactUnit, ScaleBar, View
from archaeopairs.vision.rle import rle_decode

__all__ = ["ComposeConfig", "ComposeError", "compose_unit"]


class ComposeError(ValueError):
    """A unit cannot be composed (no view, empty mask, bad binding...)."""


@dataclass
class ComposeConfig:
    margin_pct: float = 0.03
    min_margin: int = 6


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_bgr(image: Any) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ComposeError(f"image must be HxWx3/4 or HxW, got {arr.shape}")
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if arr.dtype not in (np.uint8, np.bool_):
        raise ComposeError(f"image dtype {arr.dtype} is not 8-bit")
    return np.ascontiguousarray(arr.astype(np.uint8, copy=False))


def _view_mask(view: Any, shape: tuple[int, int]) -> np.ndarray:
    rle = _get(view, "mask_rle")
    if not rle:
        raise ComposeError("view has an empty mask_rle")
    try:
        mask = rle_decode(rle)
    except ValueError as exc:
        raise ComposeError(f"cannot decode mask_rle: {exc}") from exc
    if mask.shape != shape:
        raise ComposeError(
            f"mask shape {mask.shape} does not match image {shape}")
    if not mask.any():
        raise ComposeError("view mask is empty")
    return mask


def _content_mask(image: np.ndarray, unit: Any,
                  views: Mapping[int, Any]) -> np.ndarray:
    if bool(_get(unit, "whole_image", False)):
        return np.ones(image.shape[:2], dtype=np.bool_)
    ids = list(_get(unit, "view_ids") or [])
    if not ids:
        raise ComposeError("unit has no view_ids and whole_image is False")
    mask = np.zeros(image.shape[:2], dtype=np.bool_)
    for view_id in ids:
        view = views.get(view_id)
        if view is None:
            raise ComposeError(f"view {view_id} not found")
        mask |= _view_mask(view, image.shape[:2])
    if not mask.any():
        raise ComposeError("unit content mask is empty")
    return mask


def _bbox_of(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _crop(image: np.ndarray, bbox: Any) -> np.ndarray:
    h, w = image.shape[:2]
    try:
        x0, y0, x1, y1 = (int(v) for v in bbox)
    except (TypeError, ValueError) as exc:
        raise ComposeError(f"invalid scale bbox {bbox!r}") from exc
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        raise ComposeError(f"scale bbox {bbox!r} is empty inside the image")
    return image[y0:y1, x0:x1].copy()


def compose_unit(image_bgr: Any, unit: ArtifactUnit | Mapping[str, Any],
                 views: dict[int, View],
                 scales: dict[int, ScaleBar],
                 cfg: ComposeConfig | None = None) -> tuple[np.ndarray, dict]:
    """Compose one unit onto a white canvas; return ``(canvas_bgr, meta)``."""
    cfg = cfg or ComposeConfig()
    image = _as_bgr(image_bgr)
    h, w = image.shape[:2]
    # Accept int keys and their string form (JSON round-trips).
    views = {int(k): v for k, v in (views or {}).items()}
    scales = {int(k): v for k, v in (scales or {}).items()}
    mask = _content_mask(image, unit, views)
    cx0, cy0, cx1, cy1 = _bbox_of(mask)
    cw, ch = cx1 - cx0, cy1 - cy0
    margin = max(int(cfg.min_margin),
                 round(float(cfg.margin_pct) * max(cw, ch)))

    bars: list[np.ndarray] = []
    scale_meta: list[dict] = []
    missing: list[Any] = []
    for binding in list(_get(unit, "scale_bindings") or []):
        raw_id = _get(binding, "scale_id")
        try:
            scale_id = int(raw_id)
        except (TypeError, ValueError):
            missing.append(raw_id)
            continue
        scale = scales.get(scale_id)
        if scale is None:
            missing.append(scale_id)
            continue
        crop = _crop(image, _get(scale, "bbox"))
        bars.append(crop)
        scale_meta.append({
            "scale_id": scale_id,
            "source": _get(binding, "source", "unknown"),
            "shared": bool(_get(binding, "shared", False)),
            "bbox": [int(v) for v in _get(scale, "bbox")],
            "size": [int(crop.shape[1]), int(crop.shape[0])],
        })

    content = image[cy0:cy1, cx0:cx1]
    gap = margin if bars else 0
    row_h = max((bar.shape[0] for bar in bars), default=0)
    row_w = sum(bar.shape[1] for bar in bars) + gap * max(len(bars) - 1, 0)
    canvas_w = max(margin * 2 + cw, margin * 2 + row_w)
    canvas_h = margin * 2 + ch + (gap + row_h if bars else 0)
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)

    paste_x = (canvas_w - cw) // 2
    paste_y = margin
    canvas[paste_y:paste_y + ch, paste_x:paste_x + cw] = content
    pasted = canvas[paste_y:paste_y + ch, paste_x:paste_x + cw]
    mismatch = int(np.count_nonzero(pasted != content))

    scale_row_y = paste_y + ch + gap
    row_x = (canvas_w - row_w) // 2
    for bar in bars:
        canvas[scale_row_y:scale_row_y + bar.shape[0],
               row_x:row_x + bar.shape[1]] = bar
        row_x += bar.shape[1] + gap

    meta = {
        "canvas_size": [int(canvas_w), int(canvas_h)],
        "content_box": [cx0, cy0, cx1, cy1],
        "content_paste_at": [int(paste_x), int(paste_y)],
        "margin": int(margin),
        "pixel_mismatch": mismatch,
        "scales": scale_meta,
        "missing_scales": missing,
        "whole_image": bool(_get(unit, "whole_image", False)),
    }
    return canvas, meta

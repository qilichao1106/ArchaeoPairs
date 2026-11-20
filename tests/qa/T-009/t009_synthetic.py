"""Synthetic PIL/numpy builders for the frozen T-009 tests.

The fixtures deliberately keep every pixel in memory: a white figure with two
textured views and a scale bar is enough to prove union masks, pure
translation, white padding and scale-bar cropping without reading ``books/``
or touching the filesystem.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from archaeopairs.models import ArtifactUnit, ScaleBar, View
from archaeopairs.vision.rle import rle_encode

H, W = 120, 200
BLOCK_A = (30, 20, 70, 50)  # x0, y0, x1, y1
BLOCK_B = (110, 60, 170, 100)
BAR = (20, 108, 61, 113)
BAR2 = (80, 108, 130, 113)


def _from_rgb(rgb: np.ndarray) -> np.ndarray:
    """Round-trip through PIL and hand back a contiguous BGR array."""
    rgb_image = Image.fromarray(rgb, mode="RGB")
    return np.asarray(rgb_image, dtype=np.uint8)[:, :, ::-1].copy()


def make_image() -> np.ndarray:
    """200x120 BGR figure: two textured blocks plus a measured bar."""
    rng = np.random.default_rng(20261121)
    rgb = np.full((H, W, 3), 255, dtype=np.uint8)
    for box in (BLOCK_A, BLOCK_B):
        x0, y0, x1, y1 = box
        rgb[y0:y1, x0:x1] = rng.integers(
            0, 200, size=(y1 - y0, x1 - x0, 3), dtype=np.uint8
        )
    # Two measured bars; their bboxes are the sources of the crops.
    rgb[BAR[1]:BAR[3], BAR[0]:BAR[2]] = (0, 0, 0)
    rgb[BAR[1]:BAR[3], BAR[0]:BAR[2]:7] = (210, 20, 20)
    rgb[BAR2[1]:BAR2[3], BAR2[0]:BAR2[2]] = (0, 0, 0)
    rgb[BAR2[1]:BAR2[3], BAR2[0]:BAR2[2]:9] = (20, 20, 210)
    return _from_rgb(rgb)


def make_large_image() -> np.ndarray:
    """400x500 BGR figure with a 400x300 content block (margin 3% > 6)."""
    rng = np.random.default_rng(20261122)
    rgb = np.full((400, 500, 3), 255, dtype=np.uint8)
    rgb[50:350, 50:450] = rng.integers(
        0, 200, size=(300, 400, 3), dtype=np.uint8
    )
    return _from_rgb(rgb)


def make_gradient_image() -> np.ndarray:
    """60x80 BGR gradient; any resampling would break exact equality."""
    height, width = 60, 80
    y, x = np.mgrid[0:height, 0:width]
    bgr = np.empty((height, width, 3), dtype=np.uint8)
    bgr[..., 0] = (x * 3) % 256
    bgr[..., 1] = (y * 5) % 256
    bgr[..., 2] = ((x + y) * 7) % 256
    return bgr


def mask_for(box: tuple[int, int, int, int], shape=()) -> np.ndarray:
    """A full-frame boolean mask covering ``box`` (x0, y0, x1, y1)."""
    height, width = shape or (H, W)
    x0, y0, x1, y1 = (int(value) for value in box)
    mask = np.zeros((height, width), dtype=np.bool_)
    mask[y0:y1, x0:x1] = True
    return mask


def view_for(view_id: int, box: tuple[int, int, int, int], shape=()) -> View:
    """One View whose full-frame RLE covers ``box``."""
    mask = mask_for(box, shape)
    return View(
        view_id=int(view_id),
        bbox=tuple(int(value) for value in box),
        area=int(mask.sum()),
        mask_rle=rle_encode(mask),
    )


def scale_for(bbox: tuple[int, int, int, int] = BAR, text: str = "0 5厘米") -> ScaleBar:
    """One ScaleBar whose bbox points at pixels already drawn in the image."""
    return ScaleBar(
        text=text,
        bbox=tuple(int(value) for value in bbox),
        value=5.0,
        unit="cm",
    )


def binding(scale_id, source: str = "L1_prefix", shared: bool = False) -> dict:
    """One ScaleBinding-shaped dict as T-008 hands it to composition."""
    return {"scale_id": scale_id, "source": source, "shared": shared}


def unit_for(
    artifact_id: str = "M4:6",
    *,
    view_ids=(0,),
    bindings=(),
    whole_image: bool = False,
) -> ArtifactUnit:
    """One ArtifactUnit with explicit, never inferred, view/scale ids."""
    return ArtifactUnit(
        artifact_id=artifact_id,
        seq_ids=["1"],
        view_ids=[int(view_id) for view_id in view_ids],
        whole_image=whole_image,
        scale_bindings=[dict(item) for item in bindings],
    )


def painted_mask(meta: dict) -> np.ndarray:
    """Canvas pixels covered by the content box and the scale row."""
    width, height = meta["canvas_size"]
    painted = np.zeros((height, width), dtype=np.bool_)
    px, py = meta["content_paste_at"]
    cx0, cy0, cx1, cy1 = meta["content_box"]
    content_w, content_h = cx1 - cx0, cy1 - cy0
    painted[py:py + content_h, px:px + content_w] = True
    if meta["scales"]:
        gap = meta["margin"]
        sizes = [tuple(item["size"]) for item in meta["scales"]]
        row_w = sum(item_w for item_w, _ in sizes) + gap * (len(sizes) - 1)
        row_y = py + content_h + gap
        row_x = (width - row_w) // 2
        for item_w, item_h in sizes:
            painted[row_y:row_y + item_h, row_x:row_x + item_w] = True
            row_x += item_w + gap
    return painted
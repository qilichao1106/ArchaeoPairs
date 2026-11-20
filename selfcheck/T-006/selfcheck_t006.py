"""Self-check for T-006: OpenCV segmentation, View and COCO RLE.

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-006/selfcheck_t006.py

All inputs are synthetic images written to a temporary directory (including a
Chinese path); no real book data is read.  UTF-8 log: selfcheck/T-006/selfcheck.log
"""

import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from archaeopairs.models import View  # noqa: E402
from archaeopairs.vision import (  # noqa: E402
    extract_contours, filled_mask, load_image, mask_iou, rle_decode,
    rle_encode, segment_views,
)

LOG = Path(__file__).resolve().with_name("selfcheck.log")


def write_png(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    encoded.tofile(str(path))


def canvas(height=160, width=160):
    return np.full((height, width, 3), 255, dtype=np.uint8)


def block(image, x0, y0, x1, y1, color=0):
    image[y0:y1, x0:x1] = color


def check_rle_round_trip():
    mask = np.zeros((7, 9), dtype=np.bool_)
    mask[1:3, 2:5] = True
    mask[5, 8] = True
    encoded = rle_encode(mask)
    assert encoded.startswith("7x9:")
    assert rle_decode(encoded).tobytes() == mask.tobytes()
    column = np.zeros((4, 1), dtype=np.bool_)
    column[1:3] = True
    assert rle_encode(column) == "4x1:1,2,1"
    blank = rle_encode(np.zeros((3, 5), dtype=np.bool_))
    assert blank == "3x5:15" and not rle_decode(blank).any()
    full = rle_encode(np.ones((2, 3), dtype=np.bool_))
    assert full == "2x3:0,6" and rle_decode(full).all()
    for bad in ("3x3:8", "3x3:1,2,3,4", "0x3:0", "abc", "2x2:", "2x2:2,1,-1"):
        try:
            rle_decode(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")
    try:
        rle_encode(np.zeros((2, 2, 2), dtype=np.bool_))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for 3-D mask")


def check_load_image_chinese_path(tmp):
    image = canvas(20, 30)
    block(image, 4, 5, 10, 11, (0, 0, 255))
    path = tmp / "中文 目录" / "器物图.png"
    write_png(path, image)
    loaded = load_image(path)
    assert loaded.shape == image.shape
    assert np.array_equal(loaded, image)
    assert load_image(str(path)).shape == (20, 30, 3)
    try:
        load_image(tmp / "无此文件.png")
    except OSError:
        pass
    else:
        raise AssertionError("missing file must raise OSError")
    junk = tmp / "坏图.png"
    junk.write_bytes(b"not an image")
    try:
        load_image(junk)
    except OSError:
        pass
    else:
        raise AssertionError("undecodable file must raise OSError")


def check_two_blocks_and_reading_order(tmp):
    image = canvas()
    block(image, 20, 20, 60, 60)
    block(image, 90, 100, 140, 140)
    path = tmp / "两块.png"
    write_png(path, image)
    views = segment_views(path, min_area=15.0)
    assert len(views) == 2, [v.bbox for v in views]
    assert [v.view_id for v in views] == [0, 1]
    assert all(isinstance(v, View) and not v.incomplete for v in views)
    assert views[0].bbox[0] < views[1].bbox[0]
    assert views[0].bbox[1] < views[1].bbox[1]
    for view in views:
        decoded = rle_decode(view.mask_rle)
        assert decoded.shape == image.shape[:2]
        assert int(decoded.sum()) == view.area > 0
        x0, y0, x1, y1 = view.bbox
        outside = decoded.copy()
        outside[y0:y1, x0:x1] = False
        assert not outside.any(), "mask must stay inside its bbox"
    assert rle_decode(views[0].mask_rle)[30, 30]
    assert not rle_decode(views[0].mask_rle)[120, 120]


def check_small_noise_removed(tmp):
    image = canvas()
    block(image, 30, 30, 80, 80)
    block(image, 120, 120, 123, 123)
    write_png(tmp / "噪点.png", image)
    views = segment_views(tmp / "噪点.png", min_area=15.0)
    assert len(views) == 1, [v.bbox for v in views]
    assert not rle_decode(views[0].mask_rle)[121, 121]


def check_hole(tmp):
    image = canvas()
    block(image, 20, 20, 100, 100)
    block(image, 50, 50, 70, 70, 255)
    path = tmp / "孔洞.png"
    write_png(path, image)
    kept, removed, binary = extract_contours(
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    )
    assert binary.shape == image.shape[:2]
    assert len(kept) == 1, [k["bbox"] for k in kept]
    assert removed and all(item["hole"] for item in removed)
    outer_mask = filled_mask(kept[0]["contour"], image.shape[:2])
    assert outer_mask[60, 60], "hole is filled as part of the outer view"
    views = segment_views(path)
    assert len(views) == 1 and views[0].area > 60 * 60




def check_blank_and_masks(tmp):
    white = canvas()
    write_png(tmp / "纯白.png", white)
    assert segment_views(tmp / "纯白.png") == []
    kept, removed, _ = extract_contours(cv2.cvtColor(white, cv2.COLOR_BGR2GRAY))
    assert kept == [] and removed == []

    image = canvas()
    block(image, 20, 20, 60, 60)
    write_png(tmp / "iou.png", image)
    view = segment_views(tmp / "iou.png")[0]
    mask = rle_decode(view.mask_rle)
    assert mask_iou(mask, mask) == 1.0
    assert mask_iou(mask, np.zeros_like(mask)) == 0.0
    assert mask_iou(np.zeros((2, 2), bool), np.zeros((2, 2), bool)) == 0.0
    try:
        mask_iou(mask, np.zeros((3, 3), bool))
    except ValueError:
        pass
    else:
        raise AssertionError("shape mismatch must raise ValueError")


CHECKS = (check_rle_round_trip, check_load_image_chinese_path,
          check_two_blocks_and_reading_order, check_small_noise_removed,
          check_hole, check_blank_and_masks)


def main() -> int:
    log = open(LOG, "w", encoding="utf-8", newline="\n")
    try:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            for check in CHECKS:
                log.write(f"RUN {check.__name__}\n")
                log.flush()
                check(tmp) if check.__code__.co_argcount else check()
        log.write("SELFCHECK OK\n")
    finally:
        log.close()
    print(f"SELFCHECK OK ({len(CHECKS)} checks; log: selfcheck/T-006/selfcheck.log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

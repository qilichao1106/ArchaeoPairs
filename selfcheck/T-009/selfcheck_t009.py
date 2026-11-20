"""Self-check for T-009: composition + naming (synthetic data only).

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-009/selfcheck_t009.py

Builds a 200x120 figure with two black-block views and one scale bar, then
verifies white background, exact pixel translation, margin, scale placement,
whole_image, naming rules and the empty-mask error.  UTF-8 log:
selfcheck/T-009/selfcheck.log
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from archaeopairs.compose import ComposeError, compose_unit  # noqa: E402
from archaeopairs.models import ArtifactUnit, ScaleBar, View  # noqa: E402
from archaeopairs.naming import (  # noqa: E402
    build_image_name,
    dedup_name,
    extract_fig_number,
    path_artifact,
)
from archaeopairs.vision.rle import rle_encode  # noqa: E402

LOG = Path(__file__).resolve().with_name("selfcheck.log")
H, W = 120, 200
BAR = (20, 108, 61, 113)


def make_image():
    rng = np.random.default_rng(20261121)
    image = np.full((H, W, 3), 255, dtype=np.uint8)
    image[20:50, 30:70] = rng.integers(0, 120, (30, 40, 3), dtype=np.uint8)
    image[60:100, 110:170] = rng.integers(0, 120, (40, 60, 3), dtype=np.uint8)
    image[108:113, 20:61] = (0, 0, 0)
    image[108:113, 20:61:10] = (200, 0, 0)
    return image


def mask_of(box):
    mask = np.zeros((H, W), dtype=np.bool_)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = True
    return mask


def views_and_scales():
    boxes = [(30, 20, 70, 50), (110, 60, 170, 100)]
    views = {
        i: View(view_id=i, bbox=box, area=int(mask_of(box).sum()),
                mask_rle=rle_encode(mask_of(box)))
        for i, box in enumerate(boxes)
    }
    return views, {0: ScaleBar(text="0 5厘米", bbox=BAR)}


def binding(scale_id, source="L1_prefix", shared=False):
    return {"scale_id": scale_id, "source": source, "shared": shared}


def check_compose():
    image = make_image()
    views, scales = views_and_scales()
    unit = ArtifactUnit(artifact_id="M4:6", seq_ids=["1"], view_ids=[1, 0],
                        group_ids=[0], scale_bindings=[binding(0)])
    canvas, meta = compose_unit(image, unit, views, scales)

    assert meta["content_box"] == [30, 20, 170, 100], meta["content_box"]
    cw, ch = 140, 80
    margin = max(6, round(0.03 * max(cw, ch)))
    assert meta["margin"] == margin == 6, meta["margin"]
    assert meta["pixel_mismatch"] == 0
    cx0, cy0 = meta["content_box"][:2]
    px, py = meta["content_paste_at"]
    assert py == margin and px >= margin
    np.testing.assert_array_equal(
        canvas[py:py + ch, px:px + cw], image[cy0:cy0 + ch, cx0:cx0 + cw])

    box = image[BAR[1]:BAR[3], BAR[0]:BAR[2]]
    bh, bw = box.shape[:2]
    bar_x = (canvas.shape[1] - bw) // 2
    bar_y = py + ch + margin
    np.testing.assert_array_equal(canvas[bar_y:bar_y + bh, bar_x:bar_x + bw], box)
    assert bar_y > py + ch, "scale must sit below the content"

    painted = np.zeros(canvas.shape[:2], dtype=np.bool_)
    painted[py:py + ch, px:px + cw] = True
    painted[bar_y:bar_y + bh, bar_x:bar_x + bw] = True
    assert np.all(canvas[~painted] == 255), "background must be pure white"
    assert canvas.shape[0] == py + ch + margin + bh + margin
    assert canvas.shape[1] == meta["canvas_size"][0]
    assert meta["scales"][0]["scale_id"] == 0 and meta["missing_scales"] == []
    return canvas, meta


def check_shared_and_missing():
    image = make_image()
    views, scales = views_and_scales()
    unit = ArtifactUnit(artifact_id="M4:7", view_ids=[0], scale_bindings=[
        binding(0, "L2_unique_shared", True),
        binding(0, "L2_unique_shared", True),
        binding(9),
    ])
    canvas, meta = compose_unit(image, unit, views, scales)
    assert len(meta["scales"]) == 2, "shared bar repeats once per binding"
    assert meta["missing_scales"] == [9]
    assert canvas.shape[1] >= 41 * 2 + meta["margin"] + 2 * meta["margin"]


def check_no_scale_and_dict_unit():
    image = make_image()
    views, scales = views_and_scales()
    canvas, meta = compose_unit(image, ArtifactUnit(artifact_id="X", view_ids=[0]),
                                views, scales)
    assert meta["scales"] == [] and meta["missing_scales"] == []
    assert canvas.shape[0] == 30 + 2 * meta["margin"]
    canvas, meta = compose_unit(
        image, {"artifact_id": "M4:9", "view_ids": [1], "whole_image": False,
                "scale_bindings": []}, views, scales)
    assert meta["content_box"] == [110, 60, 170, 100]
    assert canvas.shape[1] == 60 + 2 * meta["margin"]


def check_whole_image():
    image = make_image()
    canvas, meta = compose_unit(image, ArtifactUnit(artifact_id="M321:2-3",
                                                    whole_image=True), {}, {})
    assert meta["content_box"] == [0, 0, W, H]
    margin = max(6, round(0.03 * W))
    assert meta["margin"] == margin
    px, py = meta["content_paste_at"]
    np.testing.assert_array_equal(canvas[py:py + H, px:px + W], image)
    assert meta["pixel_mismatch"] == 0 and meta["whole_image"] is True


def check_errors():
    image = make_image()
    views, scales = views_and_scales()
    empty = View(view_id=5, bbox=(0, 0, 1, 1), area=0,
                 mask_rle=rle_encode(np.zeros((H, W), dtype=np.bool_)))
    bad_units = [
        ({"artifact_id": "X", "view_ids": [5]}, {5: empty}),
        ({"artifact_id": "X", "view_ids": [42]}, views),
        ({"artifact_id": "X", "view_ids": []}, views),
    ]
    for unit, vws in bad_units:
        try:
            compose_unit(image, unit, vws, scales)
        except ComposeError:
            continue
        raise AssertionError(f"ComposeError expected for {unit['view_ids']}")
    try:
        compose_unit(image, {"artifact_id": "X", "view_ids": [0],
                             "scale_bindings": [binding(0)]}, views,
                     {0: ScaleBar(text="?", bbox=(10, 10, 10, 10))})
    except ComposeError:
        pass
    else:
        raise AssertionError("empty scale bbox must raise ComposeError")


def check_naming():
    cases = {
        "图2-1-16 M4出土铜舟、盘、圆纹饰拓片": "图2-1-16",
        "图七": "图七",
        "图二六 M4出土": "图二六",
        "图版204": "图版204",
        "拓片三七": "拓片三七",
        "图七a 盖顶面": "图七a",
        "图2-1-16b": "图2-1-16b",
        "图一三 M9出土器物": "图一三",
    }
    for caption, expected in cases.items():
        assert extract_fig_number(caption) == expected, caption
    assert extract_fig_number(None) == "图"
    assert extract_fig_number("", fallback="图X") == "图X"
    assert path_artifact("M43:75a") == "M43-75a"
    assert path_artifact("M39：8-1") == "M39-8-1"
    assert path_artifact("M4∶2") == "M4-2"
    assert build_image_name("图2-1-16", "1", "M4:2") == "图2-1-16_1_M4-2.png"
    assert build_image_name("图2-1-5", None, "M4:6") == "图2-1-5_01_M4-6.png"
    assert build_image_name("图一三", "1,2", "M9:6") == "图一三_1,2_M9-6.png"
    assert build_image_name("图版204", None, "M321:2-3") == "图版204_01_M321-2-3.png"
    registry = {}
    names = [dedup_name("图七_01_M4-6.png", registry) for _ in range(3)]
    assert names == ["图七_01_M4-6.png", "图七_01_M4-6_1.png",
                     "图七_01_M4-6_2.png"], names
    assert dedup_name("图七_01_M4-7.png", registry) == "图七_01_M4-7.png"


def main():
    check_compose()
    check_shared_and_missing()
    check_no_scale_and_dict_unit()
    check_whole_image()
    check_errors()
    check_naming()
    return "SELFCHECK OK"


if __name__ == "__main__":
    lines = ["T-009 selfcheck", f"python={sys.version.split()[0]}",
             f"numpy={np.__version__}"]
    try:
        lines.append(main())
        code = 0
    except Exception:  # noqa: BLE001 - log then fail loudly
        import traceback
        lines.append("SELFCHECK FAILED")
        lines.append(traceback.format_exc())
        code = 1
    text = "\n".join(lines) + "\n"
    LOG.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(code)

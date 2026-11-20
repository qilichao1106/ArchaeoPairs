"""AC-05: white-background composition, pure translation and scale placement."""

from __future__ import annotations

import numpy as np

from archaeopairs.compose import compose_unit
from archaeopairs.models import ArtifactUnit

from t009_synthetic import (
    BAR,
    BAR2,
    BLOCK_A,
    BLOCK_B,
    binding,
    make_gradient_image,
    make_image,
    make_large_image,
    painted_mask,
    scale_for,
    unit_for,
    view_for,
)


def test_two_view_union_uses_tight_bbox_and_exact_pixels() -> None:
    image = make_image()
    views = {0: view_for(0, BLOCK_A), 1: view_for(1, BLOCK_B)}
    unit = unit_for("M4:6", view_ids=(0, 1))

    canvas, meta = compose_unit(image, unit, views, {})

    assert meta["content_box"] == [30, 20, 170, 100]
    assert meta["canvas_size"] == [152, 92]
    assert meta["content_paste_at"] == [6, 6]
    assert meta["margin"] == 6
    assert meta["pixel_mismatch"] == 0
    assert meta["scales"] == []
    assert meta["missing_scales"] == []
    assert meta["whole_image"] is False
    assert canvas.shape == (92, 152, 3)

    np.testing.assert_array_equal(canvas[6:86, 6:146], image[20:100, 30:170])
    # Both blocks keep their source coordinates inside the translated crop.
    np.testing.assert_array_equal(canvas[6:36, 6:46], image[20:50, 30:70])
    np.testing.assert_array_equal(canvas[46:86, 86:146], image[60:100, 110:170])
    # The gap between the views is source background, not synthetic fill.
    np.testing.assert_array_equal(canvas[26, 56], image[40, 80])

    assert np.all(canvas[:6] == 255)
    assert np.all(canvas[86:] == 255)
    assert np.all(canvas[:, :6] == 255)
    assert np.all(canvas[:, 146:] == 255)


def test_scale_bar_is_bbox_crop_below_content_and_centered() -> None:
    image = make_image()
    views = {1: view_for(1, BLOCK_B)}
    unit = unit_for("M4:7", view_ids=(1,), bindings=(binding(0),))

    canvas, meta = compose_unit(image, unit, views, {0: scale_for(BAR)})

    assert meta["canvas_size"] == [72, 63]
    assert meta["content_box"] == [110, 60, 170, 100]
    assert meta["content_paste_at"] == [6, 6]
    assert meta["margin"] == 6
    assert meta["pixel_mismatch"] == 0
    assert meta["missing_scales"] == []
    np.testing.assert_array_equal(canvas[6:46, 6:66], image[60:100, 110:170])

    bar_y = 6 + 40 + 6
    bar_x = (72 - 41) // 2
    assert (bar_x, bar_y) == (15, 52)
    crop = image[BAR[1]:BAR[3], BAR[0]:BAR[2]]
    np.testing.assert_array_equal(
        canvas[bar_y:bar_y + 5, bar_x:bar_x + 41], crop
    )
    assert bar_y >= 6 + 40, "the scale row must sit below the content"
    assert abs(bar_x - (72 - (bar_x + 41))) <= 1, "the bar is centred"
    assert meta["scales"] == [
        {
            "scale_id": 0,
            "source": "L1_prefix",
            "shared": False,
            "bbox": [20, 108, 61, 113],
            "size": [41, 5],
        }
    ]
    assert np.all(canvas[~painted_mask(meta)] == 255)


def test_margin_is_max_of_six_pixels_and_three_percent() -> None:
    small_image = make_image()
    small_views = {1: view_for(1, BLOCK_B)}
    small_unit = unit_for("small", view_ids=(1,))
    _, small_meta = compose_unit(small_image, small_unit, small_views, {})

    # 3% of the 60 px content width is 1.8 px -> round to 2 -> floor 6.
    assert small_meta["margin"] == 6

    large_image = make_large_image()
    large_view = view_for(0, (50, 50, 450, 350), shape=(400, 500))
    large_unit = unit_for("large", view_ids=(0,))
    canvas, meta = compose_unit(large_image, large_unit, {0: large_view}, {})

    assert meta["content_box"] == [50, 50, 450, 350]
    assert round(0.03 * 400) == 12
    assert meta["margin"] == 12
    assert meta["canvas_size"] == [424, 324]
    assert meta["content_paste_at"] == [12, 12]
    assert meta["pixel_mismatch"] == 0
    np.testing.assert_array_equal(
        canvas[12:312, 12:412], large_image[50:350, 50:450]
    )


def test_pure_translation_does_not_resample_or_flip() -> None:
    image = make_gradient_image()
    view = view_for(0, (10, 5, 50, 40), shape=(60, 80))
    unit = unit_for("gradient", view_ids=(0,))

    canvas, meta = compose_unit(image, unit, {0: view}, {})

    assert meta["content_box"] == [10, 5, 50, 40]
    assert meta["margin"] == 6
    assert meta["canvas_size"] == [52, 47]
    assert meta["content_paste_at"] == [6, 6]
    assert meta["pixel_mismatch"] == 0

    px, py = meta["content_paste_at"]
    np.testing.assert_array_equal(
        canvas[py:py + 35, px:px + 40], image[5:40, 10:50]
    )
    # Adjacent source pixels stay adjacent in the same orientation.
    np.testing.assert_array_equal(canvas[py, px], image[5, 10])
    np.testing.assert_array_equal(canvas[py, px + 1], image[5, 11])
    np.testing.assert_array_equal(canvas[py + 1, px], image[6, 10])
    np.testing.assert_array_equal(canvas[py + 34, px + 39], image[39, 49])


def test_scale_bars_follow_binding_order_on_one_centered_row() -> None:
    image = make_image()
    views = {1: view_for(1, BLOCK_B)}
    unit = unit_for(
        "ordered", view_ids=(1,), bindings=(binding(1), binding(0))
    )
    scales = {0: scale_for(BAR), 1: scale_for(BAR2, text="0 10厘米")}

    canvas, meta = compose_unit(image, unit, views, scales)

    assert meta["canvas_size"] == [109, 63]
    assert [item["scale_id"] for item in meta["scales"]] == [1, 0]
    assert [item["size"] for item in meta["scales"]] == [[50, 5], [41, 5]]

    bar_y = 6 + 40 + 6
    first_x = (109 - 97) // 2
    second_x = first_x + 50 + 6
    assert (first_x, bar_y) == (6, 52)
    assert second_x == 62
    np.testing.assert_array_equal(
        canvas[bar_y:bar_y + 5, first_x:first_x + 50],
        image[BAR2[1]:BAR2[3], BAR2[0]:BAR2[2]],
    )
    np.testing.assert_array_equal(
        canvas[bar_y:bar_y + 5, second_x:second_x + 41],
        image[BAR[1]:BAR[3], BAR[0]:BAR[2]],
    )
    assert np.all(canvas[~painted_mask(meta)] == 255)


def test_shared_scale_repeats_once_per_binding() -> None:
    image = make_image()
    views = {0: view_for(0, BLOCK_A)}
    unit = unit_for(
        "shared",
        view_ids=(0,),
        bindings=(
            binding(0, source="L2_unique_shared", shared=True),
            binding(0, source="L2_unique_shared", shared=True),
        ),
    )

    canvas, meta = compose_unit(image, unit, views, {0: scale_for(BAR)})

    assert meta["canvas_size"] == [100, 53]
    assert len(meta["scales"]) == 2
    assert [item["scale_id"] for item in meta["scales"]] == [0, 0]
    assert all(item["shared"] is True for item in meta["scales"])
    assert meta["missing_scales"] == []

    bar_y = 6 + 30 + 6
    first_x = (100 - 88) // 2
    second_x = first_x + 41 + 6
    assert (first_x, bar_y) == (6, 42)
    assert second_x == 53
    crop = image[BAR[1]:BAR[3], BAR[0]:BAR[2]]
    np.testing.assert_array_equal(
        canvas[bar_y:bar_y + 5, first_x:first_x + 41], crop
    )
    np.testing.assert_array_equal(
        canvas[bar_y:bar_y + 5, second_x:second_x + 41], crop
    )
    np.testing.assert_array_equal(
        canvas[bar_y:bar_y + 5, first_x:first_x + 41],
        canvas[bar_y:bar_y + 5, second_x:second_x + 41],
    )
    assert np.all(canvas[~painted_mask(meta)] == 255)


def test_missing_scale_ids_are_reported_without_dropping_content() -> None:
    image = make_image()
    views = {1: view_for(1, BLOCK_B)}
    unit = unit_for(
        "missing",
        view_ids=(1,),
        bindings=(binding(0), binding(9), binding("nope")),
    )

    canvas, meta = compose_unit(image, unit, views, {0: scale_for(BAR)})

    assert meta["missing_scales"] == [9, "nope"]
    assert [item["scale_id"] for item in meta["scales"]] == [0]
    assert meta["canvas_size"] == [72, 63]
    assert meta["pixel_mismatch"] == 0
    np.testing.assert_array_equal(canvas[6:46, 6:66], image[60:100, 110:170])
    assert np.all(canvas[~painted_mask(meta)] == 255)


def test_missing_scale_with_no_resolved_bar_leaves_no_scale_row() -> None:
    image = make_image()
    views = {1: view_for(1, BLOCK_B)}
    unit = unit_for("missing-only", view_ids=(1,), bindings=(binding(9),))

    canvas, meta = compose_unit(image, unit, views, {})

    assert meta["scales"] == []
    assert meta["missing_scales"] == [9]
    assert meta["canvas_size"] == [72, 52]
    assert meta["content_paste_at"] == [6, 6]
    assert meta["pixel_mismatch"] == 0
    np.testing.assert_array_equal(canvas[6:46, 6:66], image[60:100, 110:170])


def test_whole_image_copies_the_full_frame_and_ignores_missing_views() -> None:
    image = make_image()
    unit = ArtifactUnit(
        artifact_id="M321:2-3",
        whole_image=True,
        view_ids=[404],
        scale_bindings=[],
    )

    canvas, meta = compose_unit(image, unit, {}, {})

    assert meta["whole_image"] is True
    assert meta["content_box"] == [0, 0, 200, 120]
    assert meta["canvas_size"] == [212, 132]
    assert meta["content_paste_at"] == [6, 6]
    assert meta["margin"] == 6
    assert meta["pixel_mismatch"] == 0
    assert meta["scales"] == []
    assert meta["missing_scales"] == []
    np.testing.assert_array_equal(canvas[6:126, 6:206], image)
    assert np.all(canvas[:6] == 255)
    assert np.all(canvas[126:] == 255)
    assert np.all(canvas[:, :6] == 255)
    assert np.all(canvas[:, 206:] == 255)


def test_dict_unit_and_json_string_keys_match_the_model_path() -> None:
    image = make_image()
    view = view_for(0, BLOCK_A)
    bar = scale_for(BAR)
    model_unit = unit_for("M4:2", view_ids=(0,), bindings=(binding(0),))
    dict_unit = {
        "artifact_id": "M4:2",
        "view_ids": [0],
        "whole_image": False,
        "scale_bindings": [binding(0)],
    }

    model_canvas, model_meta = compose_unit(image, model_unit, {0: view}, {0: bar})
    dict_canvas, dict_meta = compose_unit(image, dict_unit, {0: view}, {0: bar})

    np.testing.assert_array_equal(dict_canvas, model_canvas)
    assert dict_meta == model_meta

    # JSON round-trips turn dict keys into strings; composition normalises them.
    string_canvas, string_meta = compose_unit(
        image, dict_unit, {"0": view}, {"0": bar}
    )
    np.testing.assert_array_equal(string_canvas, model_canvas)
    assert string_meta == model_meta
    assert string_meta["scales"][0]["scale_id"] == 0


def test_unit_without_scale_binding_has_no_scale_row() -> None:
    image = make_image()
    views = {1: view_for(1, BLOCK_B)}
    unit = unit_for("no-scale", view_ids=(1,))

    canvas, meta = compose_unit(image, unit, views, {})

    assert meta["scales"] == []
    assert meta["missing_scales"] == []
    assert meta["canvas_size"] == [72, 52]
    assert meta["pixel_mismatch"] == 0
    np.testing.assert_array_equal(canvas[6:46, 6:66], image[60:100, 110:170])
    assert np.all(canvas[46:] == 255)
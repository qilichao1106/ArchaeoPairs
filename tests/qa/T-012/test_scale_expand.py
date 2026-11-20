"""T-012 frozen acceptance: a scale OCR box grows down to its printed bar.

Card behaviour 4: the VLM box covers only ``0 4厘米`` and stops above the bar.
``_expand_scale_boxes`` must include the bar's last row, keep covering the
whole text (and the bar) horizontally, and leave the box untouched when the
image has no long horizontal ink run.
"""

from __future__ import annotations

from archaeopairs.pipeline import _expand_scale_boxes

from t012_synthetic import line_image, scale_bar

_TEXT_BLOCKS = [
    (40, 50, 48, 62),
    (52, 50, 60, 62),
    (66, 50, 74, 62),
    (80, 50, 90, 62),
    (94, 50, 104, 62),
]
_SCALE = (35, 45, 110, 65)


def test_expand_scale_box_includes_bar_line_and_text_extent(tmp_path) -> None:
    path = line_image(
        tmp_path / "scale_bar.png",
        size=(200, 120),
        texts=_TEXT_BLOCKS,
        bar=(30, 80, 140, 83),  # three ink rows: 80, 81, 82
    )
    scale = scale_bar("0 4厘米", _SCALE, prefix_nos=["1"])

    expanded = _expand_scale_boxes(path, [scale])

    assert len(expanded) == 1
    bbox = expanded[0].bbox
    assert isinstance(bbox, tuple)
    x0, y0, x1, y1 = bbox
    assert y0 <= 45 and y1 >= 83          # last bar row (82) is inside
    assert x0 <= 35 and x1 >= 110         # text stays fully covered
    assert x1 > 110                       # the box actually grew to the bar


def test_expand_scale_box_without_bar_keeps_the_original_bbox(tmp_path) -> None:
    path = line_image(
        tmp_path / "scale_text_only.png",
        size=(200, 120),
        texts=_TEXT_BLOCKS,
    )
    scale = scale_bar("0 4厘米", _SCALE, prefix_nos=["1"])

    expanded = _expand_scale_boxes(path, [scale])

    assert expanded == [scale]
    assert expanded[0].bbox == _SCALE
    assert isinstance(expanded[0].bbox, tuple)
    assert _expand_scale_boxes(path, []) == []
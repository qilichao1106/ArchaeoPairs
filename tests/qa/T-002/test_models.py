"""T-002 model contract: five image types, four work lines, FigureInput fields."""

from __future__ import annotations

import pytest

from archaeopairs.classify.image_type import work_line_of
from archaeopairs.models import FigureInput, ImageType, WorkLine


def test_image_type_has_exactly_the_five_frozen_values():
    assert {t.value for t in ImageType} == {
        "single_line_artifact",
        "multi_line_artifact",
        "single_plate_artifact",
        "multi_plate_artifact",
        "discarded",
    }


def test_work_line_has_exactly_the_four_frozen_values():
    assert {w.value for w in WorkLine} == {
        "multi_line",
        "single_line",
        "single_plate",
        "archive",
    }


def test_figure_input_exposes_the_frozen_fields():
    assert set(FigureInput.model_fields) == {
        "book_id",
        "figure_id",
        "fileref",
        "media_path",
        "caption",
        "figure_note",
        "body_paras",
    }


@pytest.mark.parametrize(
    ("image_type", "expected"),
    [
        (ImageType.SINGLE_LINE, WorkLine.SINGLE_LINE),
        (ImageType.MULTI_LINE, WorkLine.MULTI_LINE),
        (ImageType.SINGLE_PLATE, WorkLine.SINGLE_PLATE),
        (ImageType.MULTI_PLATE, WorkLine.ARCHIVE),
        (ImageType.DISCARDED, WorkLine.ARCHIVE),
    ],
)
def test_work_line_of_four_line_mapping(image_type, expected):
    assert work_line_of(image_type) == expected
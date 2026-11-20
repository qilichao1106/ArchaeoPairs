"""T-012 frozen acceptance: oversized-unit protection.

Card behaviour 5: a unit whose view union spans more than 70% of the figure is
almost certainly merged noise.  It is forced to ``review`` with an
``unit_oversized:<artifact_id>`` alarm and no PNG, while other units of the
same figure still compose normally.
"""

from __future__ import annotations

from archaeopairs.models import ArtifactMap, ArtifactUnit
from archaeopairs.pipeline import PipelineConfig, _oversized_units, process_book

from t012_synthetic import (
    FakeOCR,
    FakeWriter,
    figure,
    line_image,
    ocr_result,
    para,
    scale_bar,
    seq_label,
    view,
)


def _unit(artifact_id: str, view_ids) -> ArtifactUnit:
    return ArtifactUnit(artifact_id=artifact_id, view_ids=list(view_ids))


def _amap(*units: ArtifactUnit) -> ArtifactMap:
    return ArtifactMap(book_id="bookA", figure_id="fig1", units=list(units))


def test_oversized_units_use_the_union_bbox_and_strict_70_percent() -> None:
    views = [
        view(0, (10, 10, 600, 600)),
        view(1, (400, 400, 990, 990)),   # union (10, 10, 990, 990) > 70%
        view(2, (50, 50, 150, 150)),
        view(3, (0, 0, 700, 1000)),      # exactly 70% -> not oversized
    ]
    amap = _amap(
        _unit("M1:1", [0, 1]),
        _unit("M1:2", [2]),
        _unit("M1:3", [3]),
        _unit("M1:4", []),
        _unit("M1:5", [99]),             # unknown view id is ignored
    )

    assert _oversized_units(amap, views, (1000, 1000)) == {"M1:1"}
    assert _oversized_units(amap, views, None) == set()
    assert _oversized_units(amap, views, (0, 0)) == set()


def test_pipeline_reviews_only_the_oversized_unit(tmp_path) -> None:
    path = line_image(
        tmp_path / "oversized.png",
        size=(400, 300),
        boxes=[(10, 10, 380, 250), (300, 260, 350, 290)],
        bar=(20, 295, 380, 298),
    )
    ocr = FakeOCR(ocr_result(
        seqs=[seq_label("1", (30, 30, 40, 45)),
              seq_label("2", (310, 270, 320, 285))],
        scales=[scale_bar("0 4厘米", (15, 290, 385, 300), prefix_nos=["1", "2"])],
    ))
    fig = figure(
        path,
        caption="图一 出土器物",
        note="1. 陶鼎（M1:1） 2. 陶盒（M1:2）",
        body=[para("p1", "陶鼎标本M1:1，泥质灰陶。"),
              para("p2", "陶盒标本M1:2，泥质灰陶。")],
    )
    writer = FakeWriter()

    result = process_book([fig], PipelineConfig(ocr=ocr, writer=writer))[0]

    assert result.artifact_map is not None
    units = {unit.artifact_id: unit for unit in result.artifact_map.units}
    assert units["M1:1"].status == "review"
    assert units["M1:2"].status == "output"
    assert "unit_oversized:M1:1" in result.artifact_map.alarms
    assert "unit_oversized:M1:2" not in result.artifact_map.alarms
    assert result.alarms == []          # not a hard E-code

    assert [pair.artifact_id for pair in result.pairs] == ["M1:1", "M1:2"]
    oversized_pair, normal_pair = result.pairs
    assert oversized_pair.status == "review"
    assert oversized_pair.image_path == ""
    assert normal_pair.status == "output"
    assert normal_pair.image_path == "图一_2_M1-2.png"
    assert result.status == "pending_review"

    assert [name for name, _shape in writer.images] == ["图一_2_M1-2.png"]
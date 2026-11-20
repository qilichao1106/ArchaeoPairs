"""Frozen acceptance tests for the T-005 PaddleOCR adapter (card section 1).

The adapter must normalise PaddleOCR 3.x dict/``.json`` output and the legacy
``[[box, (text, score)], ...]`` shape into ``OcrResult(source="paddle")``,
classify every line as ``seq`` / ``scale`` / ``text``, reduce polygons to
axis-aligned boxes, and fail loudly (``PaddleUnavailableError`` / ``OcrError``)
instead of returning a silent empty result.

All engines are fakes: ``paddleocr`` is never imported and no model or network
is touched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr import paddle as paddle_mod
from archaeopairs.ocr.base import OCRProvider
from archaeopairs.ocr.paddle import PaddleOCRProvider, PaddleUnavailableError
from archaeopairs.ocr.vlm import OcrError

from fakes import (
    NoReadEngine,
    OcrEngine,
    PredictEngine,
    RaisingEngine,
    Result3x,
    ResultWithBrokenJson,
    ResultWithCallableJson,
    quad,
)

IMG = "figures/plate.png"


def _paddle(output, *, engine_cls=PredictEngine):
    return PaddleOCRProvider(engine_cls(output))


# ---------------------------------------------------------------------------
# PaddleOCR 3.x dict / .json / nested result shapes
# ---------------------------------------------------------------------------

V3_TEXTS = ["1", "(2)", "2-1", "0 8厘米", "5mm", "10 cm", "盖顶面纹饰", "cm"]
V3_SCORES = [0.98, 0.9, 0.8, 0.77, 0.5, 0.88, 0.66, 0.1]
V3_POLYS = [
    quad(10, 20, 30, 40),
    quad(38, 20, 60, 45),
    quad(0, 50, 90, 62),
    quad(0, 70, 80, 80),
    quad(5, 90, 20, 100),
    quad(100, 0, 200, 30),
    quad(0, 110, 70, 120),
    quad(0, 130, 5, 135),
]


def test_paddle_3x_dict_is_normalised_and_classified():
    payload = {
        "rec_texts": V3_TEXTS,
        "rec_scores": V3_SCORES,
        "rec_polys": V3_POLYS,
    }
    engine = PredictEngine([Result3x(payload)])

    result = PaddleOCRProvider(engine).read(IMG)

    assert result.source == "paddle"
    assert engine.calls == [IMG]
    assert result.seqs == [
        SeqLabel(text="1", bbox=(10, 20, 30, 40), conf=0.98),
        SeqLabel(text="(2)", bbox=(38, 20, 60, 45), conf=0.9),
        SeqLabel(text="2-1", bbox=(0, 50, 90, 62), conf=0.8),
    ]
    assert result.scales == [
        ScaleBar(text="0 8厘米", bbox=(0, 70, 80, 80), value=8.0, unit="厘米"),
        ScaleBar(text="5mm", bbox=(5, 90, 20, 100), value=5.0, unit="毫米"),
        ScaleBar(text="10 cm", bbox=(100, 0, 200, 30), value=10.0, unit="厘米"),
    ]
    assert result.texts == [
        TextBlock(text="盖顶面纹饰", bbox=(0, 110, 70, 120)),
        TextBlock(text="cm", bbox=(0, 130, 5, 135)),
    ]
    assert [line["kind"] for line in result.raw["lines"]] == [
        "seq",
        "seq",
        "seq",
        "scale",
        "scale",
        "scale",
        "text",
        "text",
    ]
    assert result.raw["lines"][0] == {
        "text": "1",
        "bbox": [10, 20, 30, 40],
        "kind": "seq",
        "conf": 0.98,
    }


def test_v3_dict_accepts_dt_polys_instead_of_rec_polys():
    payload = {
        "rec_texts": ["1"],
        "rec_scores": [0.9],
        "dt_polys": [quad(0, 0, 9, 9)],
    }
    result = _paddle([Result3x(payload)]).read(IMG)

    assert result.seqs == [SeqLabel(text="1", bbox=(0, 0, 9, 9), conf=0.9)]
    assert result.scales == [] and result.texts == []


def test_v3_json_wrapper_and_nested_res_are_unwrapped():
    payload = {
        "res": {
            "rec_texts": ["7"],
            "rec_scores": [0.5],
            "rec_polys": [quad(1.4, 1.6, 5, 6)],
        }
    }

    result = _paddle([Result3x(payload)]).read(IMG)

    assert result.source == "paddle"
    assert result.seqs == [SeqLabel(text="7", bbox=(1, 2, 5, 6), conf=0.5)]


# ---------------------------------------------------------------------------
# Legacy list shapes: per-image nesting, nested wrappers, flat boxes
# ---------------------------------------------------------------------------


def test_legacy_per_image_list_uses_ocr_when_predict_is_absent():
    line1 = [[1, 2, 11, 12], ("3", 0.91)]
    line2 = [quad(30, 40, 90, 55), ("10 cm", 0.8)]
    line3 = [quad(5, 60, 70, 70), ("底层开口", 0.7)]
    engine = OcrEngine([[line1, line2, line3]])  # one image -> one nested group

    result = PaddleOCRProvider(engine).read(IMG)

    assert engine.calls == [IMG]
    assert result.source == "paddle"
    assert result.seqs == [SeqLabel(text="3", bbox=(1, 2, 11, 12), conf=0.91)]
    assert result.scales == [
        ScaleBar(text="10 cm", bbox=(30, 40, 90, 55), value=10.0, unit="厘米")
    ]
    assert result.texts == [TextBlock(text="底层开口", bbox=(5, 60, 70, 70))]


def test_legacy_nested_groups_are_flattened():
    line1 = [quad(1, 2, 11, 12), ("3", 0.91)]
    line2 = [[30, 40, 80, 50], ("4", 0.7)]
    engine = OcrEngine([[[line1]], line2])

    result = PaddleOCRProvider(engine).read(IMG)

    assert result.seqs == [
        SeqLabel(text="3", bbox=(1, 2, 11, 12), conf=0.91),
        SeqLabel(text="4", bbox=(30, 40, 80, 50), conf=0.7),
    ]


def test_single_top_level_legacy_line_is_not_split_into_points():
    line = [quad(0, 0, 4, 4), ("7", 0.6)]
    result = PaddleOCRProvider(OcrEngine([line])).read(IMG)

    assert result.seqs == [SeqLabel(text="7", bbox=(0, 0, 4, 4), conf=0.6)]


def test_flat_four_and_eight_coordinate_boxes_and_polygons_are_reduced():
    payload = {
        "rec_texts": ["1", "2", "3"],
        "rec_scores": [0.9, 0.8, 0.7],
        "rec_polys": [
            [1.4, 2.6, 10.4, 20.6],  # flat axis-aligned [x0, y0, x1, y1]
            [0, 0, 10, 0, 10, 5, 0, 5],  # flat four-point polygon
            [[10, 20], [30, 20], [40, 40], [10, 40]],  # [[x, y], ...] polygon
        ],
    }
    result = _paddle([Result3x(payload)]).read(IMG)

    assert [seq.bbox for seq in result.seqs] == [
        (1, 3, 10, 21),
        (0, 0, 10, 5),
        (10, 20, 40, 40),
    ]


def test_path_is_forwarded_to_the_engine_as_a_string():
    engine = PredictEngine([Result3x({"rec_texts": [], "rec_scores": [], "rec_polys": []})])
    image = Path("figures") / "图 1.png"

    result = PaddleOCRProvider(engine).read(image)

    assert engine.calls == [str(image)]
    assert result == OcrResult(source="paddle", raw={"lines": []})


# ---------------------------------------------------------------------------
# Empty results are legal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output",
    [
        [Result3x({"rec_texts": [], "rec_scores": [], "rec_polys": []})],
        [Result3x({"rec_texts": [], "rec_scores": [], "dt_polys": []})],
        [[]],
        [],
        {},
    ],
)
def test_no_text_output_is_a_legal_empty_result(output):
    result = PaddleOCRProvider(PredictEngine(output)).read(IMG)

    assert result == OcrResult(
        seqs=[], scales=[], texts=[], source="paddle", raw={"lines": []}
    )


def test_blank_lines_are_dropped_from_the_result_and_raw_lines():
    payload = {
        "rec_texts": ["", "   ", "1"],
        "rec_scores": [0.99, 0.98, 0.9],
        "rec_polys": [quad(0, 0, 1, 1), quad(0, 1, 1, 2), quad(0, 2, 9, 9)],
    }
    result = _paddle([Result3x(payload)]).read(IMG)

    assert [seq.text for seq in result.seqs] == ["1"]
    assert len(result.raw["lines"]) == 1


# ---------------------------------------------------------------------------
# predict / ocr precedence, engine cache and lazy loading
# ---------------------------------------------------------------------------


def test_predict_takes_precedence_over_ocr():
    engine = PredictEngine([Result3x({"rec_texts": ["1"], "rec_scores": [1.0],
                                      "rec_polys": [quad(0, 0, 1, 1)]})])

    result = PaddleOCRProvider(engine).read(IMG)

    assert engine.calls == [IMG]
    assert result.seqs[0].text == "1"


def test_injected_engine_is_cached_and_reused_between_reads():
    engine = PredictEngine([Result3x({"rec_texts": [], "rec_scores": [], "rec_polys": []})])
    provider = PaddleOCRProvider(engine)

    assert provider.engine is engine
    provider.read(IMG)
    provider.read(IMG)

    assert engine.calls == [IMG, IMG]


def test_lazy_engine_is_loaded_once_on_first_read(monkeypatch):
    engine = PredictEngine([Result3x({"rec_texts": [], "rec_scores": [], "rec_polys": []})])
    seen: dict[str, object] = {"imports": 0, "factory": 0}
    seen["kwargs"] = None

    class Module:
        @staticmethod
        def PaddleOCR(**kwargs):
            seen["factory"] = int(seen["factory"]) + 1
            seen["kwargs"] = kwargs
            return engine

    def fake_import(name: str):
        seen["imports"] = int(seen["imports"]) + 1
        assert name == "paddleocr"
        return Module

    monkeypatch.setattr(
        paddle_mod, "importlib", SimpleNamespace(import_module=fake_import)
    )
    provider = PaddleOCRProvider(lang="ch")

    assert seen["imports"] == 0  # construction alone must not load Paddle
    assert seen["factory"] == 0

    provider.read(IMG)
    provider.read(IMG)

    assert seen["imports"] == 1
    assert seen["factory"] == 1
    assert seen["kwargs"] == {"lang": "ch"}
    assert provider.engine is engine


@pytest.mark.parametrize(
    "error",
    [
        ModuleNotFoundError("No module named 'paddleocr'"),
        ImportError("paddleocr is not importable"),
    ],
)
def test_lazy_import_failure_raises_paddle_unavailable(monkeypatch, error):
    def fake_import(name: str):
        raise error

    monkeypatch.setattr(
        paddle_mod, "importlib", SimpleNamespace(import_module=fake_import)
    )
    provider = PaddleOCRProvider()

    with pytest.raises(PaddleUnavailableError) as excinfo:
        provider.read(IMG)

    assert isinstance(excinfo.value, OcrError)
    assert type(error).__name__ in str(excinfo.value)


def test_engine_initialisation_failure_raises_paddle_unavailable(monkeypatch):
    class Module:
        @staticmethod
        def PaddleOCR(**kwargs):
            raise RuntimeError("model init failed")

    monkeypatch.setattr(
        paddle_mod,
        "importlib",
        SimpleNamespace(import_module=lambda name: Module),
    )

    with pytest.raises(PaddleUnavailableError) as excinfo:
        PaddleOCRProvider().read(IMG)

    assert "RuntimeError" in str(excinfo.value)


def test_module_without_paddleocr_factory_raises_paddle_unavailable(monkeypatch):
    monkeypatch.setattr(
        paddle_mod,
        "importlib",
        SimpleNamespace(import_module=lambda name: object()),
    )

    with pytest.raises(PaddleUnavailableError) as excinfo:
        PaddleOCRProvider().read(IMG)

    assert "AttributeError" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Negative paths: every unsupported/failed read must raise, never go silent
# ---------------------------------------------------------------------------


def test_engine_read_exception_is_wrapped_in_ocr_error():
    engine = RaisingEngine(ValueError("engine crashed"))

    with pytest.raises(OcrError) as excinfo:
        PaddleOCRProvider(engine).read(IMG)

    assert "paddle OCR failed" in str(excinfo.value)
    assert "ValueError" in str(excinfo.value)
    assert engine.calls == [IMG]


def test_engine_with_neither_predict_nor_ocr_raises_ocr_error():
    with pytest.raises(OcrError) as excinfo:
        PaddleOCRProvider(NoReadEngine()).read(IMG)

    assert "neither predict() nor ocr()" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"rec_texts": ["1"], "rec_scores": [], "rec_polys": [quad(0, 0, 1, 1)]},
        {"rec_texts": ["1"], "rec_scores": [0.5], "rec_polys": []},
        {"rec_texts": ["1"]},  # partial group: scores/polys missing
        {"rec_texts": ["1"], "rec_scores": [0.5], "rec_polys": [quad(0, 0, 1, 1),
                                                               quad(0, 0, 1, 1)]},
    ],
)
def test_mismatched_rec_group_lengths_raise_ocr_error(payload):
    with pytest.raises(OcrError):
        _paddle([Result3x(payload)]).read(IMG)


@pytest.mark.parametrize(
    "poly",
    [
        [[1, 2], [3, 4], [5]],  # a point without both coordinates
        [[1, 2], ["x", 4], [5, 6], [7, 8]],  # non-numeric coordinate
        [[True, 2], [3, 4], [5, 6], [7, 8]],  # bool is not a coordinate
        42,  # not a coordinate list at all
    ],
)
def test_malformed_bbox_raises_ocr_error(poly):
    payload = {"rec_texts": ["1"], "rec_scores": [0.5], "rec_polys": [poly]}

    with pytest.raises(OcrError):
        _paddle([Result3x(payload)]).read(IMG)


def test_broken_json_accessor_raises_ocr_error():
    with pytest.raises(OcrError) as excinfo:
        _paddle([ResultWithBrokenJson()]).read(IMG)

    # ``read`` must wrap the escaping ValueError; the exact wording is not part
    # of the card, only "an exception becomes OcrError".
    assert "paddle OCR failed" in str(excinfo.value)
    assert "ValueError" in str(excinfo.value)


def test_callable_json_result_raises_ocr_error():
    with pytest.raises(OcrError) as excinfo:
        _paddle([ResultWithCallableJson()]).read(IMG)

    assert "not a property" in str(excinfo.value)


def test_unavailable_error_is_an_ocr_error_and_provider_matches_protocol():
    assert issubclass(PaddleUnavailableError, OcrError)
    assert isinstance(PaddleOCRProvider(PredictEngine([])), OCRProvider)
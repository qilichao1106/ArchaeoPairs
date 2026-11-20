"""Self-check for T-005: PaddleOCR adapter and VLM+Paddle hybrid OCR.

    PYTHONDONTWRITEBYTECODE=1 python selfcheck/T-005/selfcheck_t005.py

Only fake engines/providers are used: ``paddleocr`` is never imported, no model
is loaded and no network call is made.  The UTF-8 log is written by this script.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock  # noqa: E402
from archaeopairs.ocr import (  # noqa: E402
    HybridOCRProvider, OCRProvider, OcrError, PaddleOCRProvider,
    PaddleUnavailableError, VlmOCRProvider, merge_ocr_results)
from archaeopairs.ocr import paddle as paddle_mod  # noqa: E402

LOG = Path(__file__).with_name("selfcheck.log")
IMG = "fake/plate.png"


def raises(exc_type, call):
    try:
        call()
    except exc_type as exc:
        return exc
    raise AssertionError(f"{exc_type.__name__} not raised")


class Result3x:
    """Stand-in for a PaddleOCR 3.x result object exposing ``.json``."""

    def __init__(self, payload):
        self.json = payload


class PredictEngine:
    def __init__(self, output):
        self.output, self.calls = output, []

    def predict(self, path):
        self.calls.append(path)
        return self.output

    def ocr(self, path):  # pragma: no cover - must not be called
        raise AssertionError("predict must take precedence over ocr")


class OcrEngine:
    def __init__(self, output):
        self.output, self.calls = output, []

    def ocr(self, path):
        self.calls.append(path)
        return self.output


def provider_v3():
    payload = {"rec_texts": ["1", "(2)", "0 8厘米", "5mm", "盖顶面纹饰", "cm"],
               "rec_scores": [0.98, 0.9, 0.77, 0.5, 0.66, 0.1],
               "rec_polys": [[[10, 20], [30, 20], [30, 40], [10, 40]],
                             [[40, 20], [60, 25], [58, 45], [38, 40]],
                             [[0, 50], [90, 50], [90, 60], [0, 62]],
                             [[5, 70], [20, 70], [20, 80], [5, 80]],
                             [[100, 0], [200, 0], [200, 30], [100, 30]],
                             [[0, 0], [5, 0], [5, 5], [0, 5]]]}
    return PaddleOCRProvider(PredictEngine([Result3x(payload)]))


def provider_legacy():
    payload = [
        [[[1, 2], [11, 2], [11, 12], [1, 12]], ("3", 0.91)],
        [[[30, 40], [90, 40], [90, 55], [30, 55]], ("10 cm", 0.8)],
        [[[5, 60], [70, 60], [70, 70], [5, 70]], ("底层开口", 0.7)],
        [None, (None, None)],
    ]
    return PaddleOCRProvider(OcrEngine([payload]))  # legacy single-image nesting


def check_v3_dict():
    payload = {"rec_texts": ["1"], "rec_scores": [0.9],
               "dt_polys": [[[0, 0], [0, 9], [9, 9], [9, 0]]]}
    fake = PredictEngine([payload])  # raw dict output, dt_polys instead of rec_polys
    provider = PaddleOCRProvider(fake)
    result = provider.read(IMG)
    assert result.source == "paddle" and fake.calls == [IMG]
    assert result.seqs == [SeqLabel(text="1", bbox=(0, 0, 9, 9), conf=0.9)]
    assert result.scales == [] and result.texts == []
    assert result.raw["lines"][0]["kind"] == "seq"


def check_v3_json_object():
    payload = {"res": {"rec_texts": ["2-1"], "rec_scores": [0.5],
                       "rec_polys": [[[1.4, 1.6], [5, 2], [5, 6], [1, 6]]]}}
    result = PaddleOCRProvider(PredictEngine([Result3x(payload)])).read(IMG)
    assert result.seqs == [SeqLabel(text="2-1", bbox=(1, 2, 5, 6), conf=0.5)]


def check_legacy():
    provider = provider_legacy()
    result = provider.read(IMG)
    assert result.source == "paddle" and provider.engine.calls == [IMG]
    assert result.seqs == [SeqLabel(text="3", bbox=(1, 2, 11, 12), conf=0.91)]
    assert result.scales == [ScaleBar(text="10 cm", bbox=(30, 40, 90, 55), value=10.0,
                                      unit="厘米")]
    assert result.texts == [TextBlock(text="底层开口", bbox=(5, 60, 70, 70))]


def check_top_level_legacy_line():
    # A single top-level [box, (text, score)] must not be split into box points.
    box = [[0, 0], [4, 0], [4, 4], [0, 4]]
    rows = PaddleOCRProvider(OcrEngine([[box, ("7", 0.6)]])).read(IMG)
    assert rows.seqs == [SeqLabel(text="7", bbox=(0, 0, 4, 4), conf=0.6)]
    flat = PaddleOCRProvider(OcrEngine([([0, 0, 4, 0, 4, 4, 0, 4], ("8", 0.5))]))
    assert flat.read(IMG).seqs == [SeqLabel(text="8", bbox=(0, 0, 4, 4), conf=0.5)]


def check_classification():
    provider = provider_v3()
    result = provider.read(IMG)
    assert [s.text for s in result.seqs] == ["1", "(2)"]
    assert result.seqs[1].bbox == (38, 20, 60, 45)  # min/max over the skewed quad
    assert [(s.text, s.value, s.unit) for s in result.scales] == [
        ("0 8厘米", 8.0, "厘米"), ("5mm", 5.0, "毫米")]
    assert [t.text for t in result.texts] == ["盖顶面纹饰", "cm"]
    kinds = [line["kind"] for line in result.raw["lines"]]
    assert kinds == ["seq", "seq", "scale", "scale", "text", "text"], kinds


def check_empty():
    empty = PaddleOCRProvider(PredictEngine([Result3x(
        {"rec_texts": [], "rec_scores": [], "rec_polys": []})])).read(IMG)
    assert empty == OcrResult(source="paddle", raw={"lines": []})
    assert PaddleOCRProvider(OcrEngine([[]])).read(IMG).seqs == []


def check_engine_errors():
    def boom(path):
        raise ValueError("engine crashed")

    class Broken:
        predict = staticmethod(boom)

    exc = raises(OcrError, lambda: PaddleOCRProvider(Broken()).read(IMG))
    assert "paddle OCR failed" in str(exc) and "ValueError" in str(exc)
    raises(OcrError, lambda: PaddleOCRProvider(object()).read(IMG))  # no predict/ocr
    bad = {"rec_texts": ["1"], "rec_scores": [], "rec_polys": []}
    raises(OcrError, lambda: PaddleOCRProvider(PredictEngine([Result3x(bad)])).read(IMG))
    raises(OcrError, lambda: PaddleOCRProvider(PredictEngine([Result3x(
        {"rec_texts": ["1"], "rec_scores": [0.1], "rec_polys": [[1, 2, 3]]}
    )])).read(IMG))


def check_lazy_import_failure():
    original = paddle_mod.importlib.import_module

    def missing(name):
        raise ModuleNotFoundError("No module named 'paddleocr'")

    paddle_mod.importlib.import_module = missing
    try:
        provider = PaddleOCRProvider()
        assert provider._engine is None  # not loaded at construction time
        exc = raises(PaddleUnavailableError, lambda: provider.read(IMG))
        assert isinstance(exc, OcrError) and "ModuleNotFoundError" in str(exc)
    finally:
        paddle_mod.importlib.import_module = original


def check_lazy_import_success():
    original, seen = paddle_mod.importlib.import_module, {}

    class Module:
        @staticmethod
        def PaddleOCR(**kwargs):
            seen["kwargs"] = kwargs
            return OcrEngine([[[[0, 0], [4, 0], [4, 4], [0, 4]], ("7", 0.6)]])

    def importer(name):
        seen["name"] = name
        return Module

    paddle_mod.importlib.import_module = importer
    try:
        provider = PaddleOCRProvider(lang="ch")
        result = provider.read(IMG)
        assert seen["name"] == "paddleocr" and seen["kwargs"] == {"lang": "ch"}
        assert result.seqs[0].text == "7"
        provider.read(IMG)  # cached: import_module is not called twice
    finally:
        paddle_mod.importlib.import_module = original


class FakeProvider:
    def __init__(self, result=None, error=None, name="Fake"):
        self.result, self.error = result, error
        self.__class__.__name__ = name
        self.calls = []

    def read(self, image_path):
        self.calls.append(image_path)
        if self.error is not None:
            raise self.error
        return self.result


def vlm(text):
    class Client:
        def describe_image(self, image_path, prompt, *, json_mode=True):
            return json.dumps({"seqs": [{"text": text, "bbox": [0, 0, 9, 9]}],
                               "scales": [], "texts": []})

    return VlmOCRProvider(Client())


def paddle_fake(text):
    payload = {"rec_texts": [text], "rec_scores": [0.9],
               "rec_polys": [[[0, 0], [9, 0], [9, 9], [0, 9]]]}
    return PaddleOCRProvider(PredictEngine([Result3x(payload)]))


def check_hybrid_both_ok():
    primary, secondary = vlm("1"), paddle_fake("2")
    hybrid = HybridOCRProvider(primary, secondary)
    assert isinstance(hybrid, OCRProvider) and hybrid.primary is primary
    result = hybrid.read(IMG)
    assert result.source == "hybrid"
    assert [s.text for s in result.seqs] == ["1", "2"]
    assert result.seqs[0] == SeqLabel(text="1", bbox=(0, 0, 9, 9), conf=None)
    expected = merge_ocr_results(primary.read(IMG), secondary.read(IMG))
    assert result == expected


def check_hybrid_degrade():
    def boom(path):
        raise paddle_mod.PaddleUnavailableError("PaddleOCR unavailable: ImportError")

    class Broken:
        predict = staticmethod(boom)

    result = HybridOCRProvider(vlm("1"), PaddleOCRProvider(Broken())).read(IMG)
    degraded = result.raw["degraded"]
    assert result.source == "hybrid" and [s.text for s in result.seqs] == ["1"]
    assert degraded["provider"] == "secondary:PaddleOCRProvider"
    assert degraded["error"] == "PaddleUnavailableError"
    assert degraded["kept_provider"] == "vlm"

    downstream = HybridOCRProvider(
        FakeProvider(error=RuntimeError("vlm down"), name="Vlm"), paddle_fake("2")
    ).read(IMG)
    assert [s.text for s in downstream.seqs] == ["2"]
    assert downstream.raw["degraded"]["provider"] == "primary:Vlm"
    assert downstream.raw["degraded"]["error"] == "RuntimeError"


def check_hybrid_both_fail():
    hybrid = HybridOCRProvider(FakeProvider(error=ValueError("a"), name="A"),
                               FakeProvider(error=TimeoutError("b"), name="B"))
    exc = raises(OcrError, lambda: hybrid.read(IMG))
    assert "ValueError" in str(exc) and "TimeoutError" in str(exc)


CHECKS = (check_v3_dict, check_v3_json_object, check_legacy,
          check_top_level_legacy_line, check_classification, check_empty,
          check_engine_errors, check_lazy_import_failure,
          check_lazy_import_success, check_hybrid_both_ok, check_hybrid_degrade,
          check_hybrid_both_fail)


def main() -> int:
    log = open(LOG, "w", encoding="utf-8", newline="\n")
    try:
        for check in CHECKS:
            log.write(f"RUN {check.__name__}\n")
            log.flush()
            check()
        log.write("SELFCHECK OK\n")
    finally:
        log.close()
    print(f"SELFCHECK OK ({len(CHECKS)} checks; log: selfcheck/T-005/selfcheck.log)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
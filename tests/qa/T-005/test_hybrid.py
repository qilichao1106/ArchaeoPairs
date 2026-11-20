"""Frozen acceptance tests for the T-005 hybrid OCR provider (card section 2).

Both providers are always attempted.  Two successes are merged into
``source="hybrid"``; one failure degrades to the surviving reading with a
``raw["degraded"]`` record (provider name + exception type) and does not raise;
only two failures raise :class:`OcrError` naming both exception types.

Providers are fakes; no Paddle model is loaded and no socket is opened.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr import paddle as paddle_mod
from archaeopairs.ocr.base import OCRProvider
from archaeopairs.ocr.hybrid import HybridOCRProvider
from archaeopairs.ocr.paddle import PaddleOCRProvider, PaddleUnavailableError
from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider

from fakes import FakeProvider, FakeVlmClient, PredictEngine, Result3x, quad

IMG = "figures/plate.png"

VLM_PAYLOAD = {
    "seqs": [
        {"text": "1", "bbox": [0, 0, 9, 9], "conf": 0.9},
        {"text": "2", "bbox": [0, 20, 9, 29]},
    ],
    "scales": [
        {"text": "5 cm", "bbox": [0, 30, 50, 40], "value": 5, "unit": "厘米"}
    ],
    "texts": [{"text": "盖顶", "bbox": [0, 50, 80, 60]}],
}

PADDLE_PAYLOAD = {
    "rec_texts": ["1", "3", "5 cm", "盖顶"],
    "rec_scores": [0.8, 0.7, 0.6, 0.5],
    "rec_polys": [
        quad(0, 0, 9, 9),  # duplicate of the VLM "1": must collapse
        quad(0, 40, 9, 49),  # only Paddle saw "3"
        quad(0, 30, 50, 40),  # duplicate scale: must collapse
        quad(0, 60, 80, 70),  # same text, different bbox: conflict
    ],
}


def _vlm(payload=None, *, reply=None):
    if reply is None:
        reply = json.dumps(VLM_PAYLOAD, ensure_ascii=False) if payload is None else json.dumps(
            payload, ensure_ascii=False
        )
    client = FakeVlmClient(reply=reply)
    return VlmOCRProvider(client), client


def _paddle(payload=None):
    engine = PredictEngine([Result3x(PADDLE_PAYLOAD if payload is None else payload)])
    return PaddleOCRProvider(engine), engine


def _broken_import(name):
    raise ModuleNotFoundError("No module named 'paddleocr'")


# ---------------------------------------------------------------------------
# Both providers succeed -> merge_ocr_results
# ---------------------------------------------------------------------------


def test_both_success_merge_into_a_hybrid_result():
    primary, client = _vlm()
    secondary, engine = _paddle()

    result = HybridOCRProvider(primary, secondary).read(IMG)

    assert result.source == "hybrid"
    assert len(client.calls) == 1
    assert engine.calls == [IMG]
    # Primary order wins; the duplicate "1" is collapsed, "3" is appended.
    assert [seq.text for seq in result.seqs] == ["1", "2", "3"]
    assert result.seqs[0] == SeqLabel(text="1", bbox=(0, 0, 9, 9), conf=0.9)
    assert result.seqs[2] == SeqLabel(text="3", bbox=(0, 40, 9, 49), conf=0.7)
    assert result.scales == [
        ScaleBar(text="5 cm", bbox=(0, 30, 50, 40), value=5.0, unit="厘米")
    ]
    # Same text at a different bbox is kept twice and reported, never dropped.
    assert result.texts == [
        TextBlock(text="盖顶", bbox=(0, 50, 80, 60)),
        TextBlock(text="盖顶", bbox=(0, 60, 80, 70)),
    ]
    conflicts = result.raw["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["text"] == "盖顶"
    assert conflicts[0]["reason"] == "same_text_different_bbox"
    assert conflicts[0]["bboxes"] == [[0, 50, 80, 60], [0, 60, 80, 70]]
    assert result.raw["primary"]["source"] == "vlm"
    assert result.raw["secondary"]["source"] == "paddle"


def test_both_success_with_empty_results_is_a_legal_hybrid_result():
    empty_vlm = OcrResult(source="vlm")
    empty_paddle = OcrResult(source="paddle")
    hybrid = HybridOCRProvider(
        FakeProvider(result=empty_vlm), FakeProvider(result=empty_paddle)
    )

    result = hybrid.read(IMG)

    assert result == OcrResult(
        seqs=[],
        scales=[],
        texts=[],
        source="hybrid",
        raw={
            "primary": empty_vlm.model_dump(),
            "secondary": empty_paddle.model_dump(),
            "hits_by_text": {},
            "conflicts": [],
        },
    )


# ---------------------------------------------------------------------------
# One provider fails -> degrade to the other, record raw["degraded"]
# ---------------------------------------------------------------------------


def test_primary_failure_degrades_to_paddle_and_records_degraded():
    failing = FakeProvider(error=RuntimeError("vlm down"))
    secondary, engine = _paddle()

    result = HybridOCRProvider(failing, secondary).read(IMG)

    assert result.source == "hybrid"
    assert [seq.text for seq in result.seqs] == ["1", "3"]
    assert result.raw["degraded"] == {
        "provider": "primary:FakeProvider",
        "error": "RuntimeError",
        "message": "vlm down",
        "kept_provider": "paddle",
    }
    # The surviving provider's own raw payload must not be lost.
    assert [line["text"] for line in result.raw["lines"]] == ["1", "3", "5 cm", "盖顶"]
    assert failing.calls == [IMG]
    assert engine.calls == [IMG]


def test_paddle_unavailable_degrades_to_vlm_and_records_degraded():
    primary, _ = _vlm()
    failing = FakeProvider(
        error=PaddleUnavailableError("PaddleOCR unavailable: ImportError")
    )

    result = HybridOCRProvider(primary, failing).read(IMG)

    assert result.source == "hybrid"
    assert [seq.text for seq in result.seqs] == ["1", "2"]
    assert result.scales[0].text == "5 cm"
    assert result.raw["degraded"] == {
        "provider": "secondary:FakeProvider",
        "error": "PaddleUnavailableError",
        "message": "PaddleOCR unavailable: ImportError",
        "kept_provider": "vlm",
    }
    assert result.raw["seqs"] == VLM_PAYLOAD["seqs"]


def test_malformed_vlm_reply_degrades_to_paddle_ocr_error():
    primary, _ = _vlm(reply="这不是 JSON")
    secondary, _ = _paddle()

    result = HybridOCRProvider(primary, secondary).read(IMG)

    assert result.source == "hybrid"
    assert [seq.text for seq in result.seqs] == ["1", "3"]
    degraded = result.raw["degraded"]
    assert degraded["provider"] == "primary:VlmOCRProvider"
    assert degraded["error"] == "OcrError"
    assert "not valid JSON" in degraded["message"]
    assert degraded["kept_provider"] == "paddle"


def test_lazy_paddle_failure_degrades_to_vlm(monkeypatch):
    monkeypatch.setattr(
        paddle_mod,
        "importlib",
        SimpleNamespace(import_module=_broken_import),
    )
    primary, _ = _vlm()

    result = HybridOCRProvider(primary, PaddleOCRProvider()).read(IMG)

    assert result.source == "hybrid"
    assert [seq.text for seq in result.seqs] == ["1", "2"]
    degraded = result.raw["degraded"]
    assert degraded["provider"] == "secondary:PaddleOCRProvider"
    assert degraded["error"] == "PaddleUnavailableError"
    assert degraded["kept_provider"] == "vlm"


# ---------------------------------------------------------------------------
# Both providers fail -> OcrError naming both failures
# ---------------------------------------------------------------------------


def test_both_fail_raises_ocr_error_naming_both_exception_types():
    primary = FakeProvider(error=ValueError("primary exploded"))
    secondary = FakeProvider(error=TimeoutError("secondary timed out"))

    with pytest.raises(OcrError) as excinfo:
        HybridOCRProvider(primary, secondary).read(IMG)

    message = str(excinfo.value)
    assert "ValueError" in message
    assert "TimeoutError" in message
    assert "primary:FakeProvider" in message
    assert "secondary:FakeProvider" in message
    # Both providers were attempted even though the first one failed.
    assert primary.calls == [IMG]
    assert secondary.calls == [IMG]


def test_both_real_providers_failing_raises_ocr_error(monkeypatch):
    monkeypatch.setattr(
        paddle_mod,
        "importlib",
        SimpleNamespace(import_module=_broken_import),
    )
    primary, _ = _vlm(reply="{broken")

    with pytest.raises(OcrError) as excinfo:
        HybridOCRProvider(primary, PaddleOCRProvider()).read(IMG)

    message = str(excinfo.value)
    assert "hybrid OCR failed" in message
    assert "OcrError" in message
    assert "PaddleUnavailableError" in message


def test_hybrid_provider_satisfies_the_ocr_protocol():
    empty = OcrResult(source="vlm")
    hybrid = HybridOCRProvider(
        FakeProvider(result=empty), FakeProvider(result=OcrResult(source="paddle"))
    )

    assert isinstance(hybrid, OCRProvider)
    assert hybrid.primary is not hybrid.secondary
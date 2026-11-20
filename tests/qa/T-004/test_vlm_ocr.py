"""Frozen acceptance tests for the T-004 VlmOCRProvider (card section 5).

The fake client records ``describe_image`` calls and returns canned text.  A
valid reply becomes ``OcrResult(source="vlm")``; malformed JSON, bad bboxes and
missing required fields must raise ``OcrError`` instead of silently degrading.
"""

from __future__ import annotations

import json

import pytest

from archaeopairs.models import OcrResult, ScaleBar, SeqLabel, TextBlock
from archaeopairs.ocr.base import OCRProvider
from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider
from archaeopairs.vlm.client import VlmError
from archaeopairs.vlm.prompts import OCR_PROMPT

VALID_PAYLOAD = {
    "seqs": [
        {"text": "1", "bbox": [10, 20, 30, 40], "conf": 0.9},
        {"text": "2", "bbox": [50, 60, 70, 80]},
    ],
    "scales": [
        {
            "text": "0 8厘米",
            "bbox": [0, 0, 100, 10],
            "value": 8,
            "unit": "厘米",
            "prefix_nos": ["1", "2"],
        }
    ],
    "texts": [{"text": "盖顶面纹饰", "bbox": [5, 6, 105, 66]}],
}


class FakeVlmClient:
    """Records the provider call and returns/raises exactly what the test asks."""

    def __init__(self, *, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def describe_image(self, image_path, prompt, *, json_mode=True):
        self.calls.append(
            {"image_path": image_path, "prompt": prompt, "json_mode": json_mode}
        )
        if self.error is not None:
            raise self.error
        return self.reply


def _provider(reply):
    return VlmOCRProvider(FakeVlmClient(reply=reply))


def test_valid_json_is_parsed_into_a_vlm_ocr_result():
    client = FakeVlmClient(reply=json.dumps(VALID_PAYLOAD, ensure_ascii=False))
    result = VlmOCRProvider(client).read("figure.png")

    assert isinstance(result, OcrResult)
    assert result.source == "vlm"
    assert result.raw == VALID_PAYLOAD
    assert [seq.text for seq in result.seqs] == ["1", "2"]
    assert result.seqs[0].bbox == (10, 20, 30, 40)
    assert result.seqs[0].conf == 0.9
    assert result.seqs[1].conf is None
    assert result.scales == [
        ScaleBar(
            text="0 8厘米",
            bbox=(0, 0, 100, 10),
            value=8.0,
            unit="厘米",
            prefix_nos=["1", "2"],
        )
    ]
    assert result.texts == [
        TextBlock(text="盖顶面纹饰", bbox=(5, 6, 105, 66))
    ]
    assert client.calls == [
        {"image_path": "figure.png", "prompt": OCR_PROMPT, "json_mode": True}
    ]


@pytest.mark.parametrize("marker", ["```", "```json", "```JSON"])
def test_markdown_fence_is_tolerated(marker):
    reply = f"{marker}\n{json.dumps(VALID_PAYLOAD, ensure_ascii=False)}\n```"
    result = _provider(reply).read("figure.png")

    assert result.source == "vlm"
    assert [seq.text for seq in result.seqs] == ["1", "2"]


@pytest.mark.parametrize(
    "reply",
    [
        "这不是 JSON",
        "{broken",
        '{"seqs": [}',
        "[1, 2, 3]",
        '"just-a-string"',
    ],
)
def test_invalid_json_raises_ocr_error(reply):
    with pytest.raises(OcrError):
        _provider(reply).read("figure.png")


@pytest.mark.parametrize(
    "bbox",
    [
        [1, 2, 3],
        [1, 2, 3, 4, 5],
        [10, 20, 5, 40],
        [1, 20, 30, 10],
        [1, 2, "3", 4],
        [1, 2, True, 4],
    ],
)
def test_bad_bbox_raises_ocr_error(bbox):
    reply = json.dumps({"seqs": [{"text": "1", "bbox": bbox}]})
    with pytest.raises(OcrError):
        _provider(reply).read("figure.png")


@pytest.mark.parametrize(
    "payload",
    [
        {"seqs": [{"bbox": [0, 0, 1, 1]}]},
        {"seqs": [{"text": "1"}]},
        {"texts": [{"text": "x"}]},
        {"seqs": "not-a-list"},
        {"seqs": [42]},
        {"scales": [{"text": "1", "bbox": [0, 0, 1, 1], "value": "8"}]},
        {"scales": [{"text": "1", "bbox": [0, 0, 1, 1], "prefix_nos": "1"}]},
        {"texts": [{"text": 5, "bbox": [0, 0, 1, 1]}]},
    ],
)
def test_missing_or_mistyped_required_fields_raise_ocr_error(payload):
    with pytest.raises(OcrError):
        _provider(json.dumps(payload)).read("figure.png")


def test_empty_payload_is_a_legal_empty_ocr_result():
    payload = {"seqs": [], "scales": [], "texts": []}
    result = _provider(json.dumps(payload)).read("empty.png")

    assert result == OcrResult(
        seqs=[], scales=[], texts=[], source="vlm", raw=payload
    )


def test_client_failure_is_wrapped_in_ocr_error():
    client = FakeVlmClient(error=VlmError("HTTP 500"))
    with pytest.raises(OcrError) as excinfo:
        VlmOCRProvider(client).read("figure.png")
    assert "VlmError" in str(excinfo.value)


def test_non_text_reply_raises_ocr_error():
    with pytest.raises(OcrError):
        VlmOCRProvider(FakeVlmClient(reply=None)).read("figure.png")


def test_provider_satisfies_the_ocr_protocol():
    assert isinstance(_provider("{}"), OCRProvider)
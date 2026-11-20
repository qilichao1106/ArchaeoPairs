"""Fake Paddle engines, VLM clients and OCR providers for the T-005 tests.

Nothing in this module imports ``paddleocr``, loads a model or touches the
network; it only records calls and returns the canned structure a test wants.
"""

from __future__ import annotations

from typing import Any


class Result3x:
    """Stand-in for a PaddleOCR 3.x result object exposing a ``.json`` payload."""

    def __init__(self, payload: Any) -> None:
        self.json = payload


class ResultWithBrokenJson:
    """A result object whose ``.json`` accessor itself fails."""

    @property
    def json(self) -> Any:  # pragma: no cover - only the property is exercised
        raise ValueError("broken json payload")


class ResultWithCallableJson:
    """A malformed result where ``.json`` is a method, not a property."""

    def json(self) -> Any:  # pragma: no cover - the method is never called
        return {"rec_texts": []}


class PredictEngine:
    """A 3.x-like engine: ``predict`` wins and ``ocr`` must not be called."""

    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[Any] = []

    def predict(self, image_path: Any) -> Any:
        self.calls.append(image_path)
        return self.output

    def ocr(self, image_path: Any) -> Any:  # pragma: no cover - asserted unused
        raise AssertionError("predict() must take precedence over ocr()")


class OcrEngine:
    """A legacy-like engine exposing only ``ocr``."""

    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[Any] = []

    def ocr(self, image_path: Any) -> Any:
        self.calls.append(image_path)
        return self.output


class RaisingEngine:
    """An engine whose read raises whatever exception the test supplies."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls: list[Any] = []

    def predict(self, image_path: Any) -> Any:
        self.calls.append(image_path)
        raise self.error


class NoReadEngine:
    """An engine with neither ``predict`` nor ``ocr``."""


class FakeVlmClient:
    """Records ``describe_image`` calls and returns/raises canned content."""

    def __init__(self, *, reply: Any = None, error: BaseException | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def describe_image(self, image_path: Any, prompt: Any, *, json_mode: bool = True) -> Any:
        self.calls.append(
            {"image_path": image_path, "prompt": prompt, "json_mode": json_mode}
        )
        if self.error is not None:
            raise self.error
        return self.reply


class FakeProvider:
    """Minimal ``OCRProvider`` used to force one side of a hybrid to fail."""

    def __init__(
        self, *, result: Any = None, error: BaseException | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[Any] = []

    def read(self, image_path: Any) -> Any:
        self.calls.append(image_path)
        if self.error is not None:
            raise self.error
        return self.result


def quad(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    """An axis-aligned four-point polygon in paddle's ``[[x, y], ...]`` form."""
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
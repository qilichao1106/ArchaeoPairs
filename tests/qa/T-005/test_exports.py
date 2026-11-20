"""Frozen acceptance tests for the T-005 ``archaeopairs.ocr`` exports.

The package must expose the provider protocol, both concrete providers, the
hybrid, both error types and the merge helper, all pointing at the canonical
implementations.
"""

from __future__ import annotations

import archaeopairs.ocr as ocr
from archaeopairs.ocr.base import OCRProvider, merge_ocr_results
from archaeopairs.ocr.hybrid import HybridOCRProvider
from archaeopairs.ocr.paddle import PaddleOCRProvider, PaddleUnavailableError
from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider

EXPECTED_EXPORTS = {
    "HybridOCRProvider",
    "OCRProvider",
    "OcrError",
    "PaddleOCRProvider",
    "PaddleUnavailableError",
    "VlmOCRProvider",
    "merge_ocr_results",
}


def test_all_lists_exactly_the_public_surface():
    assert set(ocr.__all__) == EXPECTED_EXPORTS
    assert len(ocr.__all__) == len(EXPECTED_EXPORTS)  # no duplicates


def test_star_import_exposes_the_public_surface():
    namespace: dict[str, object] = {}
    exec("from archaeopairs.ocr import *", namespace)  # noqa: S102 - testing __all__

    assert set(namespace) - {"__builtins__"} == EXPECTED_EXPORTS


def test_exports_are_the_canonical_implementations():
    assert ocr.OCRProvider is OCRProvider
    assert ocr.merge_ocr_results is merge_ocr_results
    assert ocr.HybridOCRProvider is HybridOCRProvider
    assert ocr.VlmOCRProvider is VlmOCRProvider
    assert ocr.PaddleOCRProvider is PaddleOCRProvider
    assert ocr.OcrError is OcrError
    assert ocr.PaddleUnavailableError is PaddleUnavailableError


def test_paddle_unavailable_error_is_an_ocr_error():
    assert issubclass(ocr.PaddleUnavailableError, ocr.OcrError)
    assert issubclass(ocr.OcrError, RuntimeError)
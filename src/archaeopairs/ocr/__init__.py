"""Pluggable OCR providers (T-004, T-005)."""

from archaeopairs.ocr.base import OCRProvider, merge_ocr_results
from archaeopairs.ocr.hybrid import HybridOCRProvider
from archaeopairs.ocr.paddle import PaddleOCRProvider, PaddleUnavailableError
from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider

__all__ = [
    "HybridOCRProvider",
    "OCRProvider",
    "OcrError",
    "PaddleOCRProvider",
    "PaddleUnavailableError",
    "VlmOCRProvider",
    "merge_ocr_results",
]
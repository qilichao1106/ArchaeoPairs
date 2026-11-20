"""Pluggable OCR providers (T-004)."""

from archaeopairs.ocr.base import OCRProvider, merge_ocr_results
from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider

__all__ = ["OCRProvider", "OcrError", "VlmOCRProvider", "merge_ocr_results"]

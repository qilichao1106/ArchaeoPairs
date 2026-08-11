"""能力接口子包：抽象层 + mock 实现。"""
from .base import OCR, SAM, VLM
from .mock import MockOCR, MockSAM, MockVLM

__all__ = ["VLM", "SAM", "OCR", "MockVLM", "MockSAM", "MockOCR"]

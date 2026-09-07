"""能力接口子包：抽象层 + mock 实现 + provider 工厂。"""
from .base import OCR, SAM, VLM, VLArbiter
from .mock import MockOCR, MockSAM, MockVLM

__all__ = ["VLM", "SAM", "OCR", "VLArbiter", "MockVLM", "MockSAM", "MockOCR"]

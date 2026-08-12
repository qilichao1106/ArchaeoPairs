"""外部系统集成子包（Label Studio 复核桥接等）。"""
from .label_studio import MockReviewBridge, ReviewBridge

__all__ = ["ReviewBridge", "MockReviewBridge"]

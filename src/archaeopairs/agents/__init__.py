"""智能体层：S1–S10 各一个模块，输入/输出严格走 State 契约（§3.2 分层）。"""
from __future__ import annotations

from dataclasses import dataclass

from ..capability import OCR, SAM, VLM
from ..config import Thresholds
from ..gateway import Gateway
from ..state import PipelineFlags


@dataclass
class Services:
    """注入智能体的能力/网关容器（编排层构造，智能体不直接依赖具体模型）。"""
    vlm: VLM
    sam: SAM
    ocr: OCR
    gateway: Gateway
    thresholds: Thresholds
    flags: PipelineFlags


from . import s1, s2, s3, s4, s5, s6, s7, s8, s9, s10  # noqa: E402

__all__ = ["Services", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"]

"""能力接口抽象层（对齐《技术方案 V0.3》能力接口定义（§5.1））。

VLM/SAM/OCR 作为抽象接口，具体实现可替换；编排与智能体不直接依赖具体
模型库。P0 用 mock.py；生产可替换 transformers / 云端实现。
"""
from __future__ import annotations

from typing import Protocol


class CapabilityResponse(Protocol):
    """能力调用统一响应（含错误/重试语义，错误响应/重试/超时契约（§5.1.4））。"""
    ok: bool
    code: str
    retryable: bool
    trace_id: str


class VLM(Protocol):
    def classify(self, *, image_ref: str, caption: str | None,
                 figure_note: str | None = None, trace_id: str) -> dict: ...
    def diagnose(self, *, image_ref: str, context: dict, trace_id: str) -> dict: ...
    def confirm_text(self, *, artifact_id: str, text: str, context: dict,
                     trace_id: str) -> dict: ...


class SAM(Protocol):
    def segment(self, *, image_ref: str, prompts: list[dict], trace_id: str) -> list[dict]: ...


class OCR(Protocol):
    def read(self, *, image_ref: str, regions: list[dict], trace_id: str) -> dict: ...

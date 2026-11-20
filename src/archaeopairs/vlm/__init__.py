"""VLM access layer (T-004): chat client and task prompts."""

from archaeopairs.vlm.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    VlmClient,
    VlmError,
    VlmUnavailableError,
)
from archaeopairs.vlm.prompts import OCR_PROMPT, QC_PROMPT, VISUAL_PROMPT

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OCR_PROMPT",
    "QC_PROMPT",
    "VISUAL_PROMPT",
    "VlmClient",
    "VlmError",
    "VlmUnavailableError",
]

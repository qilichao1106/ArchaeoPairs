"""VLM + Paddle hybrid OCR provider (T-005, AC-03).

Both providers are always attempted.  Two successes are merged into one
``source="hybrid"`` result; a single failure degrades to the other reading and
records the failure (provider name + exception type) in ``raw["degraded"]``
without raising; only when both fail is an :class:`OcrError` raised, naming
both exception types.  Degradation and failure are never silent.
"""

from __future__ import annotations

from pathlib import Path

from archaeopairs.models import OcrResult
from archaeopairs.ocr.base import OCRProvider, merge_ocr_results
from archaeopairs.ocr.vlm import OcrError

__all__ = ["HybridOCRProvider"]


class HybridOCRProvider(OCRProvider):
    """Run a primary (normally VLM) and a secondary (normally Paddle) reader."""

    def __init__(self, primary: OCRProvider, secondary: OCRProvider) -> None:
        self.primary = primary
        self.secondary = secondary

    @staticmethod
    def _name(provider: OCRProvider, role: str) -> str:
        return f"{role}:{type(provider).__name__}"

    def read(self, image_path: str | Path) -> OcrResult:
        attempts: list[tuple[str, OcrResult | None, BaseException | None]] = []
        for role, provider in (
            ("primary", self.primary),
            ("secondary", self.secondary),
        ):
            try:
                attempts.append((self._name(provider, role), provider.read(image_path), None))
            except Exception as exc:  # noqa: BLE001 - summarised, never re-raised raw
                attempts.append((self._name(provider, role), None, exc))

        (p_name, p_result, p_exc), (s_name, s_result, s_exc) = attempts
        if p_result is not None and s_result is not None:
            return merge_ocr_results(p_result, s_result)

        if p_result is None and s_result is None:
            raise OcrError(
                "hybrid OCR failed: both providers failed "
                f"({p_name}: {type(p_exc).__name__}; "
                f"{s_name}: {type(s_exc).__name__})"
            )

        if p_result is not None:
            kept, failed_name, failed_exc = p_result, s_name, s_exc
        else:
            kept, failed_name, failed_exc = s_result, p_name, p_exc
        assert kept is not None and failed_exc is not None
        degraded = {
            "provider": failed_name,
            "error": type(failed_exc).__name__,
            "message": str(failed_exc),
            "kept_provider": kept.source,
        }
        return kept.model_copy(
            update={"source": "hybrid", "raw": {**kept.raw, "degraded": degraded}}
        )
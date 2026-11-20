"""Minimal OpenAI-compatible chat client used for all VLM calls (T-004).

The endpoint is the DashScope/MAAS compatible-mode API.  The key comes from
``DASHSCOPE_API_KEY`` (or the constructor) and is never logged or echoed into
an exception message.

``chat`` returns the assistant text.  ``last_usage``, ``last_latency_ms`` and
``last_reply`` are updated after every successful call.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = (
    "https://llm-1pxqd38dwq24f1gn.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_MODEL = "deepseek-v4.1-flash-1017"


class VlmError(RuntimeError):
    """A VLM call failed (HTTP error, timeout, or malformed response)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class VlmUnavailableError(VlmError):
    """No API key is configured, so no VLM request can be made."""


@dataclass(frozen=True)
class _VlmReply:
    """Assistant content plus accounting metadata (internal transport shape)."""

    content: str
    usage: dict[str, Any]
    latency_ms: float = 0.0


def _snapshot_reply(content: str, usage: dict[str, Any], latency_ms: float) -> _VlmReply:
    """Freeze one successful call into a reply snapshot."""
    return _VlmReply(content=content, usage=dict(usage), latency_ms=latency_ms)


def _image_data_url(image_path: str | Path) -> str:
    path = Path(image_path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise VlmError(f"cannot read image {path.name}: {exc}") from exc
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


class VlmClient:
    """OpenAI-compatible chat client; retries only 429/5xx, never timeouts."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
        self.base_url = (
            base_url or os.environ.get("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self._transport = transport
        self.timeout = float(timeout)
        self.last_usage: dict[str, Any] = {}
        self.last_latency_ms: float = 0.0
        self.last_reply: _VlmReply | None = None

    # -- public API -----------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        json_mode: bool = False,
        timeout: float | None = None,
        max_retries: int = 2,
    ) -> str:
        """POST ``{base_url}/chat/completions`` and return the assistant text."""
        if timeout is None:
            timeout = self.timeout
        if not self.api_key:
            raise VlmUnavailableError(
                "DASHSCOPE_API_KEY is not set; VLM is unavailable"
            )
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        attempts = max(0, int(max_retries)) + 1
        started = time.perf_counter()
        reply: _VlmReply | None = None
        content_error: VlmError | None = None
        with httpx.Client(timeout=timeout, transport=self._transport) as client:
            for attempt in range(attempts):
                try:
                    response = client.post(url, json=payload, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    # Timeouts/transport failures are not retried per contract.
                    raise VlmError(f"VLM request failed: {type(exc).__name__}") from exc
                status = response.status_code
                if 200 <= status < 300:
                    try:
                        reply = self._parse_reply(response)
                    except VlmError as exc:
                        # Some models emit ``content: null`` on the first JSON
                        # mode try; retry once within the retry budget.
                        content_error = exc
                        if attempt + 1 < attempts:
                            time.sleep(min(0.5 * (2**attempt), 8.0))
                            continue
                        raise
                    break
                if status == 429 or status >= 500:
                    if attempt + 1 < attempts:
                        time.sleep(min(0.5 * (2**attempt), 8.0))
                        continue
                    raise VlmError(
                        f"VLM request failed after {attempts} attempt(s): HTTP {status}",
                        status_code=status,
                    )
                raise VlmError(f"VLM request rejected: HTTP {status}", status_code=status)

        if reply is None:  # pragma: no cover - loop always sets or raises
            raise content_error or VlmError("VLM request produced no response")
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.last_usage = dict(reply.usage)
        self.last_latency_ms = latency_ms
        self.last_reply = _snapshot_reply(reply.content, reply.usage, latency_ms)
        return reply.content

    def describe_image(
        self,
        image_path: str | Path,
        prompt: str,
        *,
        json_mode: bool = True,
    ) -> str:
        """Send one image plus ``prompt`` and return the assistant text."""
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
        ]
        return self.chat([{"role": "user", "content": content}], json_mode=json_mode)

    # -- internals ------------------------------------------------------
    @staticmethod
    def _parse_reply(response: httpx.Response) -> _VlmReply:
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise VlmError("VLM response missing choices[0].message.content") from exc
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in (None, "text")
            )
        if not isinstance(content, str) or not content.strip():
            raise VlmError("VLM response content is not non-empty text")
        usage = body.get("usage") or {}
        if not isinstance(usage, dict):
            raise VlmError("VLM response usage is not an object")
        return _VlmReply(content=content, usage=usage)

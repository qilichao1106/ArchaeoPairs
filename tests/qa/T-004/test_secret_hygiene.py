"""T-004 secret hygiene: the API key must never leak through errors or logs.

A fake sentinel key is installed in the client; the mock server even echoes it
back in error bodies.  Neither client exceptions nor the OCR wrapper may repeat
it.
"""

from __future__ import annotations

import httpx
import pytest

from archaeopairs.ocr.vlm import OcrError, VlmOCRProvider
from archaeopairs.vlm.client import VlmClient, VlmError


class _FailingClient:
    def __init__(self, error):
        self.error = error

    def describe_image(self, image_path, prompt, *, json_mode=True):
        raise self.error


@pytest.mark.parametrize("status", [400, 401, 429])
def test_client_errors_do_not_echo_the_api_key(
    status, sentinel_key, caplog
):
    def handler(request):
        return httpx.Response(
            status,
            json={"error": {"message": f"invalid API key: {sentinel_key}"}},
        )

    client = VlmClient(
        api_key=sentinel_key,
        base_url="https://vlm.mock.invalid/v1",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(VlmError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}], max_retries=0)

    rendered = f"{excinfo.value!s}\n{excinfo.value!r}\n{client!r}\n{caplog.text}"
    assert sentinel_key not in rendered
    assert "Bearer" not in rendered


def test_missing_key_error_does_not_echo_a_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    client = VlmClient(api_key=None)
    with pytest.raises(VlmError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])

    assert "sk-" not in str(excinfo.value)
    assert "Bearer" not in f"{excinfo.value!s}{excinfo.value!r}"


def test_ocr_wrapper_does_not_echo_the_api_key(sentinel_key):
    inner = VlmError(f"HTTP 401 for bearer {sentinel_key}")
    provider = VlmOCRProvider(_FailingClient(inner))

    with pytest.raises(OcrError) as excinfo:
        provider.read("figure.png")

    assert sentinel_key not in str(excinfo.value)
    assert sentinel_key not in repr(excinfo.value)
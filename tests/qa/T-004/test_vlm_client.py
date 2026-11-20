"""Frozen acceptance tests for the T-004 VlmClient (card section 2).

Transport is always ``httpx.MockTransport``.  The tests pin the request shape,
the retry policy (429/5xx only), the ``content: null`` retry, usage/latency
accounting, image data-URL construction, and the no-key behaviour.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from archaeopairs.vlm.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    VlmClient,
    VlmError,
    VlmUnavailableError,
)

MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "hi"},
]


def _reply(content, *, usage=None, status=200):
    body = {
        "id": "chatcmpl-t004",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status, json=body)


def test_missing_api_key_raises_unavailable_without_request(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    requested = []

    def handler(request):
        requested.append(request)
        raise AssertionError("no HTTP request may be sent without a key")

    client = VlmClient(api_key=None, transport=httpx.MockTransport(handler))
    with pytest.raises(VlmUnavailableError) as excinfo:
        client.chat(MESSAGES)

    assert isinstance(excinfo.value, VlmError)
    assert "DASHSCOPE_API_KEY" in str(excinfo.value)
    assert requested == []
    assert client.last_usage == {}


def test_chat_success_sends_contract_request_and_returns_content(
    make_client, sentinel_key
):
    seen = []
    usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}

    def handler(request):
        seen.append(request)
        return _reply('{"seqs": []}', usage=usage)

    client = make_client(handler)
    result = client.chat(MESSAGES, json_mode=True)

    assert result == '{"seqs": []}'
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://vlm.mock.invalid/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {sentinel_key}"
    assert request.headers["Content-Type"].startswith("application/json")

    payload = json.loads(request.content)
    assert payload["model"] == "mock-vlm-1"
    assert payload["messages"] == MESSAGES
    assert payload["response_format"] == {"type": "json_object"}


def test_chat_records_usage_and_positive_latency(make_client):
    def handler(request):
        time.sleep(0.01)
        return _reply("ok", usage={"total_tokens": 1})

    client = make_client(handler)
    assert client.chat(MESSAGES) == "ok"

    assert client.last_usage == {"total_tokens": 1}
    assert isinstance(client.last_latency_ms, float)
    assert client.last_latency_ms > 0


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_chat_4xx_raises_immediately_without_retry(status, make_client, no_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "rejected"})

    client = make_client(handler)
    with pytest.raises(VlmError) as excinfo:
        client.chat(MESSAGES, max_retries=2)

    assert excinfo.value.status_code == status
    assert len(calls) == 1
    assert no_sleep == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_status_retries_then_succeeds(status, make_client, no_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, json={"error": "retry me"})
        return _reply("recovered")

    client = make_client(handler)
    assert client.chat(MESSAGES, max_retries=2) == "recovered"

    assert len(calls) == 2
    assert len(no_sleep) == 1
    assert 0 < no_sleep[0] <= 8


@pytest.mark.parametrize("status", [429, 500])
def test_retryable_status_exhausts_retry_budget(status, make_client, no_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "always"})

    client = make_client(handler)
    with pytest.raises(VlmError) as excinfo:
        client.chat(MESSAGES, max_retries=1)

    assert excinfo.value.status_code == status
    assert len(calls) == 2
    assert len(no_sleep) == 1
    assert f"HTTP {status}" in str(excinfo.value)


def test_null_content_is_retried_then_succeeds(make_client, no_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": None}}
                    ]
                },
            )
        return _reply('{"ok": true}')

    client = make_client(handler)
    assert client.chat(MESSAGES, max_retries=2) == '{"ok": true}'

    assert len(calls) == 2
    assert len(no_sleep) == 1


def test_null_content_exhausts_retry_budget(make_client, no_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": None}}
                ]
            },
        )

    client = make_client(handler)
    with pytest.raises(VlmError) as excinfo:
        client.chat(MESSAGES, max_retries=1)

    assert len(calls) == 2
    assert len(no_sleep) == 1
    assert "content" in str(excinfo.value).lower()


def test_timeout_is_not_retried(make_client, no_sleep):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    client = make_client(handler)
    with pytest.raises(VlmError) as excinfo:
        client.chat(MESSAGES, max_retries=2)

    assert "Timeout" in str(excinfo.value)
    assert len(calls) == 1
    assert no_sleep == []


def test_describe_image_sends_text_then_png_data_url(make_client, tmp_path):
    raw = b"\x89PNG\r\n\x1a\nT004-fake-image-bytes"
    image = tmp_path / "figure.png"
    image.write_bytes(raw)
    seen = []

    def handler(request):
        seen.append(request)
        return _reply("{}")

    client = make_client(handler)
    assert client.describe_image(image, "识别这张图") == "{}"

    payload = json.loads(seen[0].content)
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "识别这张图"}
    assert content[1]["type"] == "image_url"

    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == raw
    assert payload["response_format"] == {"type": "json_object"}


def test_describe_image_respects_json_mode_false(make_client, tmp_path):
    image = tmp_path / "figure.png"
    image.write_bytes(b"fake")
    seen = []

    def handler(request):
        seen.append(request)
        return _reply("{}")

    client = make_client(handler)
    client.describe_image(image, "prompt", json_mode=False)

    payload = json.loads(seen[0].content)
    assert "response_format" not in payload


def test_default_base_url_and_model(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    client = VlmClient(api_key="fake")
    assert client.base_url == DEFAULT_BASE_URL
    assert client.model == DEFAULT_MODEL


def test_environment_base_url_and_key_override(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://env.example/v9/")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "  env-key  ")
    client = VlmClient()
    assert client.base_url == "https://env.example/v9"
    assert client.api_key == "env-key"
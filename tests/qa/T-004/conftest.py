"""Shared setup for the frozen T-004 acceptance tests.

Run from the project root (this worktree root):

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/qa/T-004 -q -p no:cacheprovider

Every HTTP call in this suite goes through ``httpx.MockTransport``; no test
opens a socket or reads a real API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import httpx
import pytest

from archaeopairs.vlm.client import VlmClient

# Clearly fake sentinel used only to prove that errors never echo credentials.
TEST_KEY = "sk-test-T004-SENTINEL-9f3b7c"
TEST_BASE_URL = "https://vlm.mock.invalid/v1"
TEST_MODEL = "mock-vlm-1"


@pytest.fixture
def sentinel_key() -> str:
    """The fake key injected into clients that must not leak it."""
    return TEST_KEY


@pytest.fixture
def make_client():
    """Build a VlmClient whose only transport is an httpx.MockTransport."""

    def _make(handler, *, api_key=TEST_KEY, base_url=TEST_BASE_URL, model=TEST_MODEL):
        return VlmClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            transport=httpx.MockTransport(handler),
        )

    return _make


@pytest.fixture
def no_sleep(monkeypatch):
    """Record backoff delays without actually sleeping."""
    delays: list[float] = []
    monkeypatch.setattr(
        "archaeopairs.vlm.client.time.sleep",
        lambda seconds: delays.append(seconds),
    )
    return delays
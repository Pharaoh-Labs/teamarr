"""Tests for the shared provider HTTP client base (providers/base_client.py)."""

import httpx
import pytest

from teamarr.providers import base_client
from teamarr.providers.base_client import BaseHTTPClient


class _StubClient(BaseHTTPClient):
    PROVIDER = "stub"
    LOG_TAG = "STUB"


def _make_client(handler, **kwargs) -> _StubClient:
    """Build a stub client whose pooled httpx.Client uses a mock transport."""
    client = _StubClient(**kwargs)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_success_returns_json():
    client = _make_client(lambda req: httpx.Response(200, json={"ok": True}))
    assert client._request_json("https://api.test/x") == {"ok": True}


def test_http_error_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(base_client.time, "sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(500)

    client = _make_client(handler, retry_count=3)
    assert client._request_json("https://api.test/x") is None
    assert len(calls) == 3


def test_transport_error_retries_then_recovers(monkeypatch):
    monkeypatch.setattr(base_client.time, "sleep", lambda s: None)
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"recovered": True})

    client = _make_client(handler, retry_count=3)
    assert client._request_json("https://api.test/x") == {"recovered": True}


def test_429_respects_retry_after_then_recovers(monkeypatch):
    sleeps = []
    monkeypatch.setattr(base_client.time, "sleep", sleeps.append)
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"ok": True})

    client = _make_client(handler)
    assert client._request_json("https://api.test/x") == {"ok": True}
    assert sleeps == [2.0]


def test_429_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(base_client.time, "sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429)

    client = _make_client(handler)
    assert client._request_json("https://api.test/x") is None
    # Initial attempt + RATE_LIMIT_MAX_RETRIES retries
    assert len(calls) == base_client.RATE_LIMIT_MAX_RETRIES + 1


@pytest.mark.parametrize("attempt", [0, 1, 2, 5, 10])
def test_calculate_delay_bounds(attempt):
    client = _StubClient()
    for _ in range(20):
        delay = client._calculate_delay(attempt)
        assert 0.1 <= delay <= base_client.RETRY_MAX_DELAY * (1 + base_client.RETRY_JITTER)


def test_close_clears_pooled_client():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    assert client._request_json("https://api.test/x") == {}
    client.close()
    assert client._client is None

from __future__ import annotations

import httpx
import pytest

from job_agent.net.http_client import ResilientHttpClient, TransientHTTPError


def _client(handler, **kwargs) -> ResilientHttpClient:
    transport = httpx.MockTransport(handler)
    sleeps: list[float] = []
    kwargs.setdefault("sleep_fn", sleeps.append)
    client = ResilientHttpClient(client=httpx.Client(transport=transport), **kwargs)
    client.sleeps = sleeps  # type: ignore[attr-defined]
    return client


def test_success_on_first_try():
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    assert client.get_json("https://example.test/x") == {"ok": True}


def test_retries_then_succeeds_on_5xx():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, max_retries=5, backoff_seconds=0.01)
    result = client.get_json("https://example.test/x")
    assert result == {"ok": True}
    assert calls["n"] == 3
    assert len(client.sleeps) == 2  # type: ignore[attr-defined]


def test_exhausts_retries_and_raises():
    def handler(request):
        return httpx.Response(500)

    client = _client(handler, max_retries=3, backoff_seconds=0.01)
    with pytest.raises(TransientHTTPError):
        client.get_json("https://example.test/x")


def test_4xx_raises_immediately_without_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    client = _client(handler, max_retries=5, backoff_seconds=0.01)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://example.test/x")
    assert calls["n"] == 1


def test_429_respects_retry_after_header():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, max_retries=3, backoff_seconds=10)
    result = client.get_json("https://example.test/x")
    assert result == {"ok": True}
    assert client.sleeps == [0.01]  # type: ignore[attr-defined]

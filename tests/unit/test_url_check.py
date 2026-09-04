"""Live application-URL reachability check (Part 3.9's "URL works"). Uses
`httpx.MockTransport` so these tests never touch the real network — the
`transport` parameter exists on `check_application_url` for exactly this."""

from __future__ import annotations

import httpx

from job_agent.jobs.url_check import check_application_url


def test_2xx_response_is_reachable():
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.status == "REACHABLE"


def test_404_is_unreachable():
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.status == "UNREACHABLE"


def test_500_is_unreachable():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.status == "UNREACHABLE"


def test_405_on_head_falls_back_to_get():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.status == "REACHABLE"


def test_timeout_is_unknown_not_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.status == "UNKNOWN"


def test_connection_failure_is_unknown_not_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.status == "UNKNOWN"


def test_result_carries_a_checked_at_timestamp():
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    result = check_application_url("https://example.test/apply", transport=transport)
    assert result.checked_at is not None

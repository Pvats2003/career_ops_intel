"""Live application-URL reachability check (Part 3.9's "URL works"). Uses
`httpx.MockTransport` so these tests never touch the real network — the
`transport` parameter exists on `check_application_url` for exactly this."""

from __future__ import annotations

import httpx

from job_agent.jobs.url_check import _is_unsafe_target, check_application_url


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


# --- SSRF guard: a job's application_url comes from an external source
# this system does not control, so a malicious/compromised source could
# point it at an internal address. These exercise the real (no mock
# transport) code path with IP literals, which need no DNS lookup and so
# stay network-independent while still proving the guard actually runs.


def test_is_unsafe_target_rejects_loopback():
    assert _is_unsafe_target("http://127.0.0.1/admin") is not None


def test_is_unsafe_target_rejects_ipv6_loopback():
    assert _is_unsafe_target("http://[::1]/admin") is not None


def test_is_unsafe_target_rejects_link_local_metadata_address():
    assert _is_unsafe_target("http://169.254.169.254/latest/meta-data/") is not None


def test_is_unsafe_target_rejects_private_network():
    assert _is_unsafe_target("http://10.0.0.5/") is not None


def test_is_unsafe_target_rejects_non_http_scheme():
    assert _is_unsafe_target("file:///etc/passwd") is not None


def test_is_unsafe_target_accepts_public_ip_literal():
    assert _is_unsafe_target("http://93.184.216.34/") is None


def test_check_application_url_refuses_loopback_without_making_a_request():
    result = check_application_url("http://127.0.0.1:8000/apply")
    assert result.status == "UNKNOWN"
    assert "non-public" in result.detail


def test_check_application_url_refuses_cloud_metadata_address():
    result = check_application_url("http://169.254.169.254/latest/meta-data/iam/")
    assert result.status == "UNKNOWN"
    assert "non-public" in result.detail


def test_check_application_url_guard_is_skipped_for_mock_transport():
    """The guard only protects real network calls; a test's mock
    transport is exercised even for a loopback-looking URL, since no real
    socket is ever opened for it."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    result = check_application_url("http://127.0.0.1/apply", transport=transport)
    assert result.status == "REACHABLE"


def test_check_application_url_follows_safe_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    result = check_application_url("https://example.test/start", transport=transport)
    assert result.status == "REACHABLE"


def test_check_application_url_stops_after_too_many_redirects():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/next"})

    transport = httpx.MockTransport(handler)
    result = check_application_url("https://example.test/start", transport=transport)
    assert result.status == "UNKNOWN"
    assert "redirect" in result.detail.lower()

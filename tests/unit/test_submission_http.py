"""Phase 6C — `job_agent.applications.submission_http.SubmissionHttpClient`
unit tests.

Covers the central safety distinction the module's own docstring
describes (definitely-not-sent vs. ambiguous-outcome failures), the
structural "no arbitrary URL" guarantee, and the "exactly one attempt per
call, never retried internally" guarantee. Every test uses
`httpx.MockTransport` — no real network call is ever reachable from this
file.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from job_agent.applications.errors import (
    ProviderError,
    ProviderTimeoutError,
    SubmissionOutcomeUnknownError,
)
from job_agent.applications.submission_http import SubmissionHttpClient, SubmissionHttpResponse


def _client_with_handler(handler, url="https://submit.test/apply"):
    return SubmissionHttpClient(url, client=httpx.Client(transport=httpx.MockTransport(handler)))


# --------------------------------------------------------------------------
# Structural guarantees
# --------------------------------------------------------------------------
def test_post_method_has_no_url_parameter():
    sig = inspect.signature(SubmissionHttpClient.post)
    assert "url" not in sig.parameters


def test_no_method_on_the_class_accepts_a_url_at_call_time():
    """Broader structural sweep: no public method anywhere on this class
    takes a `url`-shaped parameter — the ONLY place a URL can ever be
    supplied is the constructor."""
    for name, method in inspect.getmembers(SubmissionHttpClient, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        sig = inspect.signature(method)
        for param_name in sig.parameters:
            assert "url" not in param_name.lower(), f"{name}() accepts a url-shaped parameter"


def test_client_is_bound_to_exactly_one_url():
    client = SubmissionHttpClient("https://submit.test/apply")
    assert client.target_url == "https://submit.test/apply"


def test_post_makes_exactly_one_request_per_call_never_retries_internally():
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"ok": True})

    client = _client_with_handler(handler)
    client.post({"q": "a"})
    assert call_count == 1

    client.post({"q": "b"})
    assert call_count == 2  # a second explicit call is a NEW attempt, not a retry of the first


# --------------------------------------------------------------------------
# A completed round trip (any status code) is returned, never raised.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status_code", (200, 201, 400, 401, 404, 422, 500, 503))
def test_any_http_response_is_returned_not_raised(status_code):
    def handler(request):
        return httpx.Response(status_code, json={"detail": "x"})

    client = _client_with_handler(handler)
    response = client.post({"q": "a"})
    assert isinstance(response, SubmissionHttpResponse)
    assert response.status_code == status_code


def test_response_body_and_headers_are_carried_through():
    def handler(request):
        return httpx.Response(200, json={"confirmation_id": "abc123"}, headers={"X-Test": "1"})

    client = _client_with_handler(handler)
    response = client.post({"q": "a"})
    assert "abc123" in response.text
    assert response.headers.get("x-test") == "1"


def test_request_payload_and_headers_are_actually_sent():
    captured = {}

    def handler(request):
        captured["body"] = request.content
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True})

    client = _client_with_handler(handler)
    client.post({"q": "hello"}, headers={"Authorization": "Bearer tok"})
    assert b"hello" in captured["body"]
    assert captured["auth"] == "Bearer tok"


# --------------------------------------------------------------------------
# Definitely-not-sent failures (pre-connect) — ordinary, unambiguous.
# --------------------------------------------------------------------------
def test_connect_error_raises_plain_provider_error_not_ambiguous():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = _client_with_handler(handler)
    with pytest.raises(ProviderError) as exc_info:
        client.post({"q": "a"})
    assert not isinstance(exc_info.value, SubmissionOutcomeUnknownError)


def test_connect_timeout_raises_provider_timeout_error():
    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    client = _client_with_handler(handler)
    with pytest.raises(ProviderTimeoutError):
        client.post({"q": "a"})


def test_pool_timeout_raises_provider_timeout_error():
    def handler(request):
        raise httpx.PoolTimeout("timeout", request=request)

    client = _client_with_handler(handler)
    with pytest.raises(ProviderTimeoutError):
        client.post({"q": "a"})


# --------------------------------------------------------------------------
# Ambiguous (possibly-sent) failures — must ALWAYS raise
# SubmissionOutcomeUnknownError, never a plain ProviderError.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc_factory",
    (
        lambda request: httpx.ReadTimeout("timeout", request=request),
        lambda request: httpx.WriteTimeout("timeout", request=request),
        lambda request: httpx.ReadError("failed", request=request),
        lambda request: httpx.WriteError("failed", request=request),
        lambda request: httpx.RemoteProtocolError("bad response", request=request),
        lambda request: httpx.LocalProtocolError("bad request"),
    ),
)
def test_post_connect_failures_are_always_ambiguous(exc_factory):
    def handler(request):
        raise exc_factory(request)

    client = _client_with_handler(handler)
    with pytest.raises(SubmissionOutcomeUnknownError):
        client.post({"q": "a"})


def test_unrecognized_httpx_error_defaults_to_ambiguous_never_to_safe():
    """Fail-closed default: an httpx error this module does not
    specifically recognize as pre-connect must be treated as ambiguous,
    never assumed 'definitely not sent'."""

    class _WeirdHTTPError(httpx.HTTPError):
        pass

    def handler(request):
        raise _WeirdHTTPError("something unrecognized")

    client = _client_with_handler(handler)
    with pytest.raises(SubmissionOutcomeUnknownError):
        client.post({"q": "a"})


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------
def test_context_manager_closes_a_client_it_created_itself():
    with SubmissionHttpClient("https://submit.test/apply") as client:
        pass
    assert client._client.is_closed


def test_context_manager_does_not_close_a_caller_supplied_client():
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    external = httpx.Client(transport=httpx.MockTransport(handler))
    with SubmissionHttpClient("https://submit.test/apply", client=external) as client:
        client.post({"q": "a"})
    assert not external.is_closed


def test_close_does_not_close_a_caller_supplied_external_client():
    """A caller that passes its own `httpx.Client` retains ownership of
    it — `SubmissionHttpClient.close()` must not close a resource it
    didn't create, since the caller may still be using it elsewhere."""

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    external = httpx.Client(transport=httpx.MockTransport(handler))
    client = SubmissionHttpClient("https://submit.test/apply", client=external)
    client.close()
    assert not external.is_closed


def test_close_does_close_a_client_it_created_itself():
    owned_client = SubmissionHttpClient("https://submit.test/apply")
    owned_client.close()
    assert owned_client._client.is_closed

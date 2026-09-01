from __future__ import annotations

import json

from instacore_sync.utils.google_api_errors import (
    is_auth_error,
    is_not_found_error,
    is_permanent_google_api_error,
    is_transient_google_api_error,
)


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakeHttpError(Exception):
    def __init__(self, status: int, reason: str | None = None) -> None:
        self.resp = _FakeResp(status)
        body = {"error": {"errors": [{"reason": reason}]}} if reason else {"error": {}}
        self.content = json.dumps(body).encode("utf-8")


def test_rate_limit_403_is_transient() -> None:
    exc = _FakeHttpError(403, reason="userRateLimitExceeded")
    assert is_transient_google_api_error(exc) is True


def test_permission_denied_403_is_not_transient() -> None:
    exc = _FakeHttpError(403, reason="forbidden")
    assert is_transient_google_api_error(exc) is False


def test_server_error_5xx_is_transient() -> None:
    for status in (500, 502, 503, 504):
        assert is_transient_google_api_error(_FakeHttpError(status)) is True


def test_too_many_requests_429_is_transient() -> None:
    assert is_transient_google_api_error(_FakeHttpError(429)) is True


def test_bad_request_400_is_not_transient() -> None:
    assert is_transient_google_api_error(_FakeHttpError(400)) is False


def test_not_found_404_is_not_transient_but_is_detected_separately() -> None:
    exc = _FakeHttpError(404)
    assert is_transient_google_api_error(exc) is False
    assert is_not_found_error(exc) is True


def test_is_auth_error_detects_401() -> None:
    assert is_auth_error(_FakeHttpError(401)) is True
    assert is_auth_error(_FakeHttpError(403)) is False


def test_malformed_error_body_does_not_raise() -> None:
    exc = _FakeHttpError(403)
    exc.content = b"not json"
    assert is_transient_google_api_error(exc) is False  # fails safe, doesn't crash


class _TypedWrapperError(Exception):
    """Stands in for DriveApiError/SheetsApiError — every real call site
    catches the raw HttpError and re-raises one of these via `raise ... from
    exc`, which is what the __cause__ chain below is regression-testing."""


def test_transient_error_is_detected_through_a_typed_wrapper_via_cause() -> None:
    """Regression test for a real bug: every @google_api_retry()-decorated
    method in this codebase catches HttpError and re-raises a typed
    DriveApiError/SheetsApiError via `raise TypedError(...) from exc` — so
    the exception tenacity's retry predicate actually evaluates is the
    wrapper, not the original HttpError, unless this function also checks
    __cause__. Before this fix, every transient 429/500/502/503/504 from
    Drive or Sheets silently never retried at the API-call level."""
    original = _FakeHttpError(429)
    try:
        raise _TypedWrapperError("Drive call failed: 429") from original
    except _TypedWrapperError as wrapped:
        assert is_transient_google_api_error(wrapped) is True


def test_permanent_error_through_a_typed_wrapper_is_still_not_transient() -> None:
    original = _FakeHttpError(404)
    try:
        raise _TypedWrapperError("not found") from original
    except _TypedWrapperError as wrapped:
        assert is_transient_google_api_error(wrapped) is False


def test_wrapper_with_no_cause_is_not_transient() -> None:
    assert is_transient_google_api_error(_TypedWrapperError("boom")) is False


def test_permission_denied_403_is_permanent() -> None:
    assert is_permanent_google_api_error(_FakeHttpError(403, reason="forbidden")) is True


def test_not_found_404_is_permanent() -> None:
    assert is_permanent_google_api_error(_FakeHttpError(404)) is True


def test_bad_request_400_is_permanent() -> None:
    assert is_permanent_google_api_error(_FakeHttpError(400)) is True


def test_rate_limited_403_is_not_permanent() -> None:
    assert is_permanent_google_api_error(_FakeHttpError(403, reason="userRateLimitExceeded")) is False


def test_server_error_5xx_is_not_permanent() -> None:
    assert is_permanent_google_api_error(_FakeHttpError(503)) is False


def test_unclassifiable_error_is_not_assumed_permanent() -> None:
    """A plain error with no HTTP status at all (a timeout, a connection
    reset — never even reached Google as an HttpError) must NOT be
    treated as permanent by default. `is_permanent_google_api_error`
    only says True when the API has positively confirmed it's futile —
    'unknown' must fall back to the normal retry treatment, not skip it."""
    assert is_permanent_google_api_error(RuntimeError("connection reset")) is False


def test_permanent_error_through_a_typed_wrapper_is_detected_via_cause() -> None:
    original = _FakeHttpError(404)
    try:
        raise _TypedWrapperError("not found") from original
    except _TypedWrapperError as wrapped:
        assert is_permanent_google_api_error(wrapped) is True

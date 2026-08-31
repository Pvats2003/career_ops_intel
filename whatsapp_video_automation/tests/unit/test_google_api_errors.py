from __future__ import annotations

import json

from instacore_sync.utils.google_api_errors import (
    is_auth_error,
    is_not_found_error,
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

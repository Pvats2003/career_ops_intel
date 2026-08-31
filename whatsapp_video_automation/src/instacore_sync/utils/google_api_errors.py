"""Classifies Google API (`googleapiclient.errors.HttpError`) failures as
transient (worth retrying) or permanent (retrying is pure wasted time).

The previous retry policy treated every `HttpError` the same and retried it
up to 5 times with exponential backoff — including permission-denied (403),
invalid-request (400), and not-found (404) errors that will *never*
succeed on a retry. At best that wastes 30-60s per failed video before
finally giving up; at 200-500 videos/day, a misconfigured Drive folder
permission could silently burn minutes of wall-clock time per affected
video for no benefit. Only genuinely transient conditions — rate limiting,
backend hiccups, server errors — are worth the backoff-and-retry dance.
"""

from __future__ import annotations

import json

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# 403 is ambiguous in the Drive/Sheets APIs: it covers both "you don't have
# permission" (permanent) and "you're being rate limited" (transient) — the
# `reason` field in the error body is what disambiguates them.
_TRANSIENT_403_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "backendError", "sharingRateLimitExceeded"}
)


def _http_status(exc: Exception) -> int | None:
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    return int(status) if status is not None else None


def _error_reason(exc: Exception) -> str | None:
    """Best-effort extraction of the Google API error `reason` code from an
    `HttpError`'s JSON body. Returns None if the body isn't the expected
    shape rather than raising — error classification must never itself
    raise and mask the original error."""
    content = getattr(exc, "content", None)
    if not content:
        return None
    try:
        body = json.loads(content)
        errors = body.get("error", {}).get("errors", [])
        if errors:
            return errors[0].get("reason")
        return body.get("error", {}).get("status")
    except (ValueError, AttributeError, TypeError):
        return None


def is_transient_google_api_error(exc: Exception) -> bool:
    """True if retrying the same request later stands a real chance of succeeding."""
    status = _http_status(exc)
    if status in _TRANSIENT_STATUS_CODES:
        return True
    if status == 403:
        return _error_reason(exc) in _TRANSIENT_403_REASONS
    return False


def is_not_found_error(exc: Exception) -> bool:
    """True if the API reported the target resource (e.g. a Drive folder) doesn't exist."""
    return _http_status(exc) == 404


def is_auth_error(exc: Exception) -> bool:
    """True if the API rejected the request as unauthenticated/unauthorized."""
    return _http_status(exc) == 401

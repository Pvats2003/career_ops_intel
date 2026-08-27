"""Structured JSON logging with automatic secret redaction.

Every important operation should log with `event_id`, `component`, `action`,
`result`, `duration`, `error` per BUILD PROMPT section 34. `log_event()` is
the single helper the rest of the codebase should call so that shape stays
consistent, and it double-writes to the `system_events` table when a session
is provided (kept optional here — Phase 1 callers may log without a DB
session available yet).

Security fix (post-Phase-6A audit): this module is the ONE centralized
redaction boundary for the whole codebase — `redact_value()`/`redact_text()`
are exported specifically so other modules that persist or display
diagnostic text (e.g. `job_agent.applications.repository.record_event`,
which writes the immutable `application_events` audit trail) can reuse the
exact same definition of "what looks like a secret" instead of each
maintaining their own copy. Two gaps this fix closes:

1. `log_event()`'s `error` parameter previously bypassed redaction entirely
   — only `**details` was redacted, so `log_event(..., error=str(exc))`
   (used throughout the codebase, including Phase 6A's batch-isolation
   helpers) could put a credential embedded in an exception message
   straight into the logs unredacted. `error` is now redacted identically
   to every other value.
2. `_redact()` (now `redact_value()`) previously only matched dict/list
   *keys* against a fixed set, plus one anchored regex
   (`^sk-...$`) that could only ever match a string that was *entirely*
   an Anthropic API key — never one embedded inside a longer message
   (exactly the shape a real leak takes: "... failed: api_key=sk-abc123
   ..."). Every string value — not just exact dict/list matches — is now
   run through `redact_text()`, a content-pattern scrubber that catches
   key=value/key:value assignments, Authorization/Cookie headers, Bearer
   tokens, and JWT-shaped tokens embedded anywhere in free text, not just
   in structured key/value pairs.

Nothing about the diagnostic value of logging changed: component, action,
result, duration, event/job/application IDs, provider names, and status
strings are untouched — only content that looks like a credential is ever
replaced.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

# Dict/list keys whose *entire value* is always redacted outright,
# regardless of what the value looks like — these are the field names the
# codebase (and BUILD PROMPT) itself considers inherently secret. Matched
# case-insensitively, exact key match only (no substring matching, so e.g.
# "tokenized_count" or "expected_ctc" are never accidentally caught).
_REDACT_KEYS = {
    "password",
    "passwd",
    "secret",
    "secrets",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "client_id",
    "authorization",
    "cookie",
    "cookies",
    "session_token",
    "session_id",
    "session_credentials",
    "auth_token",
    "bearer_token",
    "private_key",
    "api_key",
    "apikey",
    "anthropic_api_key",
    "credential",
    "credentials",
}
_REDACTED = "***REDACTED***"

# Content-pattern scrubber: catches a secret *embedded* anywhere inside an
# otherwise-ordinary string (an exception message, a formatted traceback, a
# log line) — not just a value that already arrived as a dict entry under a
# known key. Applied to every string that flows through redact_value()/
# redact_text(), so a raw `str(exc)` gets the same protection as a
# structured `{"password": ...}` dict.
_SECRET_KEY_NAMES = (
    r"password|passwd|secret|api[_-]?key|apikey|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|session[_-]?token|session[_-]?id|"
    r"auth[_-]?token|private[_-]?key|credentials?|token"
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf"(?i)\b({_SECRET_KEY_NAMES})\b\s*[:=]\s*(['\"]?)([^\s'\",;]+)\2"
)
_AUTHORIZATION_HEADER_PATTERN = re.compile(r"(?i)\b(authorization)\s*:\s*\S+(?:\s+\S+)?")
_COOKIE_HEADER_PATTERN = re.compile(r"(?i)\b(cookie)\s*:\s*[^\n]+")
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.=]+")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\b")
# Broadened from the original `^sk-...$` (anchored, so it could only match a
# string that was *entirely and only* a key) to `\b...\b` so it also catches
# a key embedded inside a longer message.
_OPAQUE_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")
# A credential embedded positionally in a connection URL
# (scheme://user:password@host/db) — e.g. DATABASE_URL for a non-SQLite
# deployment. No literal "password=" text appears here, so none of the
# patterns above would catch it; this is a distinct shape.
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)@")


def redact_text(text: str) -> str:
    """Scrub credential-shaped content out of a free-text string (an
    exception message, a formatted traceback, a CLI-bound diagnostic
    string) — the counterpart to `redact_value()`'s key-based redaction for
    text that never arrives as a structured dict. Safe to call on any
    string; ordinary diagnostic text (job IDs, statuses, company names)
    passes through unchanged since none of it matches a secret-shaped
    pattern."""
    if not text:
        return text
    result = text
    result = _BEARER_TOKEN_PATTERN.sub(f"Bearer {_REDACTED}", result)
    result = _AUTHORIZATION_HEADER_PATTERN.sub(lambda m: f"{m.group(1)}: {_REDACTED}", result)
    result = _COOKIE_HEADER_PATTERN.sub(lambda m: f"{m.group(1)}: {_REDACTED}", result)
    result = _JWT_PATTERN.sub(_REDACTED, result)
    result = _OPAQUE_API_KEY_PATTERN.sub(_REDACTED, result)
    result = _URL_CREDENTIAL_PATTERN.sub(
        lambda m: f"{m.group(1)}{m.group(2)}:{_REDACTED}@", result
    )
    result = _SECRET_ASSIGNMENT_PATTERN.sub(lambda m: f"{m.group(1)}={_REDACTED}", result)
    return result


def redact_value(obj: Any) -> Any:
    """Recursively redact a value of any shape before it is logged,
    persisted, or displayed: dict keys matching `_REDACT_KEYS` have their
    entire value replaced outright (covers nested sensitive structures —
    a secret buried three dicts deep is still caught, since every dict/list
    is walked); every string, wherever it appears, additionally passes
    through `redact_text()` so a credential embedded in free text (an
    exception message, for instance) is caught even when it never arrived
    under a suspicious key."""
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if k.lower() in _REDACT_KEYS else redact_value(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_value(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_value(v) for v in obj)
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        extra = getattr(record, "event_data", None)
        if extra:
            payload.update(redact_value(extra))
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))
    root.handlers.clear()
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    *,
    component: str,
    action: str,
    result: str,
    duration_ms: float | None = None,
    error: str | None = None,
    **details: Any,
) -> str:
    """Emit one structured log line and return its event_id.

    `result` should be one of "success", "failure", "skipped" — kept as a
    free string rather than an enum since new components will introduce new
    result kinds over time without needing a core schema change.
    """
    event_id = str(uuid.uuid4())
    level = logging.ERROR if error else logging.INFO
    logger.log(
        level,
        f"{component}.{action}",
        extra={
            "event_data": {
                "event_id": event_id,
                "component": component,
                "action": action,
                "result": result,
                "duration_ms": duration_ms,
                "error": redact_text(error) if error is not None else None,
                **redact_value(details),
            }
        },
    )
    return event_id

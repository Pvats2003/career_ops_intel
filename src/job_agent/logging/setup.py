"""Structured JSON logging with automatic secret redaction.

Every important operation should log with `event_id`, `component`, `action`,
`result`, `duration`, `error` per BUILD PROMPT section 34. `log_event()` is
the single helper the rest of the codebase should call so that shape stays
consistent, and it double-writes to the `system_events` table when a session
is provided (kept optional here — Phase 1 callers may log without a DB
session available yet).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

_REDACT_KEYS = {
    "password",
    "api_key",
    "authorization",
    "cookie",
    "session_token",
    "secret",
    "anthropic_api_key",
}
_REDACTED = "***REDACTED***"

_configured = False


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str) and re.match(r"^sk-[A-Za-z0-9_-]{10,}$", obj):
        return _REDACTED
    return obj


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "event_data", None)
        if extra:
            payload.update(_redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
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
                "error": error,
                **_redact(details),
            }
        },
    )
    return event_id

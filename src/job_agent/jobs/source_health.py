"""Source Health — Career OS FINAL GOD MODE Part 6.19.

Turns the health signals `job_agent.jobs.service.scan_source` already
records on each `JobSource` row (last_health_check_at/last_health_status/
last_success_at — never a second, separate health-check pass) into a
per-source status a candidate can actually act on: 🟢 healthy / 🟡
unhealthy / ⚪ never checked, when it last succeeded, its last error, and
one concrete suggested next step. The suggestion is a plain heuristic
over the (already-redacted) error text — never a guess about what's
actually wrong, just a pointer to where to look.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from job_agent.db.models import JobSource as JobSourceRow

HealthStatus = Literal["HEALTHY", "UNHEALTHY", "UNKNOWN"]

_SUGGESTION_RULES: tuple[tuple[str, str], ...] = (
    ("not set", "Check that the required API credentials are set in your environment."),
    ("unauthorized", "Check that your API credentials are valid and not expired."),
    ("forbidden", "Check that your API credentials are valid and not expired."),
    ("401", "Check that your API credentials are valid and not expired."),
    ("403", "Check that your API credentials are valid and not expired."),
    ("429", "This source is rate-limiting requests — reduce query volume or try again later."),
    (
        "rate limit",
        "This source is rate-limiting requests — reduce query volume or try again later.",
    ),
    (
        "timeout",
        "The source may be slow or down — this often clears up on its own; try again shortly.",
    ),
    (
        "timed out",
        "The source may be slow or down — this often clears up on its own; try again shortly.",
    ),
    ("connection", "Could not reach the source — check your network or the source's status."),
    ("dns", "Could not resolve the source's address — check your network or the source's status."),
    ("500", "The source is reporting a server error on its end — try again shortly."),
    ("502", "The source is reporting a server error on its end — try again shortly."),
    ("503", "The source is reporting a server error on its end — try again shortly."),
)

_DEFAULT_SUGGESTION = "Check the source's configuration in config/sources.yaml."


def suggest_action(error_message: str) -> str:
    lowered = error_message.lower()
    for keyword, suggestion in _SUGGESTION_RULES:
        if keyword in lowered:
            return suggestion
    return _DEFAULT_SUGGESTION


@dataclass(frozen=True)
class SourceHealthSummary:
    source: JobSourceRow
    status: HealthStatus
    last_error: str | None
    suggested_action: str | None
    last_success_at: datetime | None
    last_checked_at: datetime | None


def summarize_source_health(source: JobSourceRow) -> SourceHealthSummary:
    if source.last_health_status is None:
        return SourceHealthSummary(
            source=source,
            status="UNKNOWN",
            last_error=None,
            suggested_action=None,
            last_success_at=None,
            last_checked_at=None,
        )

    is_healthy = source.last_health_status == "healthy"
    last_error = None if is_healthy else source.last_health_status.removeprefix("unhealthy: ")
    return SourceHealthSummary(
        source=source,
        status="HEALTHY" if is_healthy else "UNHEALTHY",
        last_error=last_error,
        suggested_action=suggest_action(last_error) if last_error else None,
        last_success_at=source.last_success_at,
        last_checked_at=source.last_health_check_at,
    )

"""Freshness classification — BUILD PROMPT section 9.

Thresholds come from config/automation.yaml (`freshness:` block) so they're
tunable without a code change. `UNKNOWN_POST_DATE` is returned whenever
`posted_at` is missing — the system must never claim a job is freshly
posted when it has no verified posting date to back that claim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_agent.config.models import FreshnessSettings
from job_agent.jobs.schema import FreshnessStatus


def classify_freshness(
    posted_at: datetime | None,
    *,
    now: datetime | None = None,
    settings: FreshnessSettings,
) -> FreshnessStatus:
    if posted_at is None:
        return FreshnessStatus.UNKNOWN_POST_DATE

    reference = now or datetime.now(UTC)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)

    age = reference - posted_at
    if age < timedelta(0):
        # Clock skew / bad source data — treat as just posted rather than
        # asserting a negative age, but don't pretend we're certain.
        return FreshnessStatus.JUST_POSTED
    if age <= timedelta(hours=settings.just_posted_hours):
        return FreshnessStatus.JUST_POSTED
    if age <= timedelta(hours=settings.preferred_hours):
        return FreshnessStatus.NEW
    if age <= timedelta(days=settings.recent_days):
        return FreshnessStatus.RECENT
    return FreshnessStatus.OLD

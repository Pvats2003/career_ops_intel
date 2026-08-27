"""Application rate limiting — BUILD PROMPT section 43.

Checked immediately before a submission attempt (never before, since
preparation/answer-generation isn't the risky action rate limits exist to
bound). A limit hit routes the application to SKIPPED, never silently
retried or queued around the limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from job_agent.applications.repository import (
    count_submissions_from_source_since,
    count_submissions_since,
    count_submissions_to_company,
)
from job_agent.config.models import ApplicationLimits
from job_agent.db.models import Job as JobRow


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    reason: str | None = None


def check_rate_limits(
    session: Session,
    candidate_id: int,
    job: JobRow,
    limits: ApplicationLimits,
    *,
    now: datetime | None = None,
) -> RateLimitResult:
    now = now or datetime.now(UTC)

    day_count = count_submissions_since(session, candidate_id, now - timedelta(days=1))
    if day_count >= limits.max_per_day:
        return RateLimitResult(False, f"daily submission limit reached ({limits.max_per_day})")

    hour_count = count_submissions_since(session, candidate_id, now - timedelta(hours=1))
    if hour_count >= limits.max_per_hour:
        return RateLimitResult(False, f"hourly submission limit reached ({limits.max_per_hour})")

    company_count = count_submissions_to_company(session, candidate_id, job.company_name)
    if company_count >= limits.max_per_company:
        return RateLimitResult(
            False, f"per-company submission limit reached ({limits.max_per_company})"
        )

    if job.source_id is not None:
        source_count = count_submissions_from_source_since(
            session, candidate_id, job.source_id, now - timedelta(days=1)
        )
        if source_count >= limits.max_per_source_per_day:
            return RateLimitResult(
                False,
                f"per-source daily submission limit reached ({limits.max_per_source_per_day})",
            )

    return RateLimitResult(True)

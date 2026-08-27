"""Canonical Job object — every source adapter's `normalize()` must produce
one of these. See BUILD PROMPT section 7.

This is the contract the rest of the system (dedup, freshness, matching)
depends on, regardless of which source a job came from. `raw_data` always
preserves the untouched source payload for debugging (section 7's explicit
requirement), and nothing here is inferred beyond what the source actually
reported — a field the source doesn't provide stays `None`, it is never
guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class RemoteType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class FreshnessStatus(StrEnum):
    """See BUILD PROMPT section 9. UNKNOWN_POST_DATE is used whenever a
    source doesn't give a verifiable posting date — the system must never
    claim a job is freshly posted when it can't actually verify that."""

    JUST_POSTED = "JUST_POSTED"
    NEW = "NEW"
    RECENT = "RECENT"
    OLD = "OLD"
    UNKNOWN_POST_DATE = "UNKNOWN_POST_DATE"


class Job(BaseModel):
    """A normalized job posting, as produced by a `JobSource.normalize()`.

    This model intentionally does NOT carry `job_fingerprint`,
    `first_seen_at`, or `freshness_status` — those are computed by the
    discovery pipeline (`job_agent.jobs.service`) after normalization, not
    by the adapter, since they depend on prior state (has this job been
    seen before?) that a single adapter call has no way to know.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    source_job_id: str
    company: str
    title: str
    description: str | None = None
    requirements: str | None = None
    preferred_qualifications: str | None = None
    location: str | None = None
    locations: tuple[str, ...] = Field(default_factory=tuple)
    remote_type: RemoteType = RemoteType.UNKNOWN
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    visa_information: str | None = None
    posted_at: datetime | None = None
    application_url: str
    company_url: str | None = None
    discovered_at: datetime = Field(default_factory=utcnow)
    raw_data: dict = Field(default_factory=dict)

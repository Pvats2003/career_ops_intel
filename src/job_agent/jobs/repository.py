"""Persists normalized Job objects with dedup-aware upsert semantics.

Per-source identity is `(source_id, source_job_id)`: re-scanning and seeing
the same posting again updates the existing row (`last_checked_at`, and any
fields the source may have changed) rather than inserting a duplicate.
`first_seen_at`/`discovered_at` are set once and never overwritten — BUILD
PROMPT section 54 (never lose historical data) means "when was this job
first seen" must stay stable across rescans.

Cross-source duplicate *detection* (the same underlying job posted on two
portals) uses `job_fingerprint` — see `job_agent.jobs.fingerprint` — but
this repository deliberately does NOT merge or drop cross-source duplicates
automatically. It records the fingerprint on every row and leaves the
"is this the same job as row X from a different source" decision to the
matching/application layer (Phase 3+), which can then choose not to apply
twice without destroying either source's history.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.db.models import Company
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobSource as JobSourceRow
from job_agent.jobs.fingerprint import compute_job_fingerprint
from job_agent.jobs.schema import FreshnessStatus, Job


def get_or_create_job_source(
    session: Session, *, name: str, kind: str, enabled: bool
) -> JobSourceRow:
    row = session.execute(
        select(JobSourceRow).where(JobSourceRow.name == name)
    ).scalar_one_or_none()
    if row is None:
        row = JobSourceRow(name=name, kind=kind, enabled=enabled)
        session.add(row)
        session.flush()
    else:
        row.kind = kind
        row.enabled = enabled
    return row


def get_or_create_company(session: Session, name: str) -> Company:
    row = session.execute(select(Company).where(Company.name == name)).scalar_one_or_none()
    if row is None:
        row = Company(name=name)
        session.add(row)
        session.flush()
    return row


def upsert_job(
    session: Session,
    job: Job,
    *,
    source_row: JobSourceRow,
    freshness_status: FreshnessStatus,
    now: datetime | None = None,
) -> tuple[JobRow, bool]:
    """Insert or update one job. Returns (row, created)."""
    now = now or datetime.now(UTC)
    fingerprint = compute_job_fingerprint(job)
    company_row = get_or_create_company(session, job.company)

    existing = session.execute(
        select(JobRow).where(
            JobRow.source_id == source_row.id,
            JobRow.source_job_id == job.source_job_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        row = JobRow(
            source_id=source_row.id,
            source_job_id=job.source_job_id,
            company_id=company_row.id,
            company_name=job.company,
            title=job.title,
            description=job.description,
            requirements=job.requirements,
            preferred_qualifications=job.preferred_qualifications,
            location=job.location,
            locations=list(job.locations),
            remote_type=job.remote_type.value,
            employment_type=job.employment_type,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            currency=job.currency,
            visa_information=job.visa_information,
            posted_at=job.posted_at,
            application_url=job.application_url,
            company_url=job.company_url,
            discovered_at=now,
            first_seen_at=now,
            last_checked_at=now,
            job_fingerprint=fingerprint,
            freshness_status=freshness_status.value,
            raw_data=job.raw_data,
        )
        session.add(row)
        session.flush()
        return row, True

    existing.company_id = company_row.id
    existing.company_name = job.company
    existing.title = job.title
    existing.description = job.description
    existing.requirements = job.requirements
    existing.preferred_qualifications = job.preferred_qualifications
    existing.location = job.location
    existing.locations = list(job.locations)
    existing.remote_type = job.remote_type.value
    existing.employment_type = job.employment_type
    existing.salary_min = job.salary_min
    existing.salary_max = job.salary_max
    existing.currency = job.currency
    existing.visa_information = job.visa_information
    existing.posted_at = job.posted_at
    existing.application_url = job.application_url
    existing.company_url = job.company_url
    existing.last_checked_at = now
    existing.job_fingerprint = fingerprint
    existing.freshness_status = freshness_status.value
    existing.raw_data = job.raw_data
    return existing, False


def find_by_fingerprint(session: Session, fingerprint: str) -> list[JobRow]:
    """All job rows sharing a content fingerprint — candidate cross-source
    duplicates for the matching layer to reconcile (see module docstring)."""
    return list(
        session.execute(select(JobRow).where(JobRow.job_fingerprint == fingerprint)).scalars()
    )

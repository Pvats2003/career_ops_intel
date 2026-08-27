"""Phase 6C — exact-posting allowlist.

An `ApplicationAllowlistEntry` authorizes real submission attempts for
exactly ONE posting (keyed by `job_fingerprint` — the same content
fingerprint `job_agent.jobs.fingerprint.compute_job_fingerprint` already
computes for cross-source duplicate detection), for exactly one provider,
at exactly one canonical URL — never a company, a search query, or a
domain. Nothing here decides whether a posting SHOULD be allowlisted —
that is a human, via the CLI. This module only creates entries on
explicit request and checks validity; it never grants submission
authority by itself.

Validity (expired / revoked) is always computed from `expires_at`/
`revoked_at`, never cached in a separate status column — see
`job_agent.db.models.ApplicationAllowlistEntry`'s docstring for why.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.db.models import ApplicationAllowlistEntry

DEFAULT_ALLOWLIST_TTL_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    """See `job_agent.applications.approvals._as_aware_utc` — identical
    reasoning, duplicated locally rather than imported across modules
    (matches this project's existing small-helper-duplication convention)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_allowlist_entry(
    session: Session,
    job_fingerprint: str,
    provider_name: str,
    canonical_url: str,
    *,
    ttl_days: int = DEFAULT_ALLOWLIST_TTL_DAYS,
) -> ApplicationAllowlistEntry:
    entry = ApplicationAllowlistEntry(
        job_fingerprint=job_fingerprint,
        provider_name=provider_name,
        canonical_url=canonical_url,
        expires_at=utcnow() + timedelta(days=ttl_days),
    )
    session.add(entry)
    session.flush()
    return entry


def get_active_allowlist_entry(
    session: Session, job_fingerprint: str, provider_name: str, *, now: datetime | None = None
) -> ApplicationAllowlistEntry | None:
    """Returns the most recent unexpired, unrevoked entry for exactly this
    (job_fingerprint, provider_name) pair — or `None`. Note this does NOT
    check `canonical_url` against a job's current `application_url`; that
    comparison needs the live `Job` row and is the caller's responsibility
    (`job_agent.applications.service.submit_application`) — a mismatch
    there means "the target drifted since allowlisting" and must block,
    never silently follow the new URL."""
    now = now or utcnow()
    rows = session.execute(
        select(ApplicationAllowlistEntry)
        .where(
            ApplicationAllowlistEntry.job_fingerprint == job_fingerprint,
            ApplicationAllowlistEntry.provider_name == provider_name,
        )
        .order_by(ApplicationAllowlistEntry.id.desc())
    ).scalars()
    for entry in rows:
        if entry.revoked_at is not None:
            continue
        if _as_aware_utc(entry.expires_at) <= now:
            continue
        return entry
    return None


def revoke_allowlist_entry(
    session: Session, entry: ApplicationAllowlistEntry, *, now: datetime | None = None
) -> None:
    entry.revoked_at = now or utcnow()
    session.flush()

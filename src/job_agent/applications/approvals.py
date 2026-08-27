"""Phase 6C — application-approval binding and validity.

An `ApplicationApproval` authorizes exactly ONE real submission attempt
for exactly ONE `Application` — bound to the EXACT job content
(`posting_fingerprint`) and EXACT generated answers (`answer_fingerprint`)
a human reviewed at approval time. Nothing here decides WHETHER an
application should be approved — that is a human, via the CLI
(`job_agent.cli.main`'s `applications approve` command). This module only
computes the binding fingerprint and checks validity; it never creates an
approval on its own initiative, and it never grants submission authority
by itself — `job_agent.applications.service.submit_application` is still
the only code path that ever calls `provider.submit()`.

Validity (expired / consumed / revoked) is always computed from
`expires_at`/`consumed_at`/`revoked_at`, never cached in a separate status
column — see `job_agent.db.models.ApplicationApproval`'s docstring for why.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.applications.schema import GeneratedAnswer
from job_agent.db.models import ApplicationApproval

DEFAULT_APPROVAL_TTL_HOURS = 24


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite has no native timezone-aware datetime storage — a value
    written as UTC-aware can come back naive after a round trip through
    the DB (e.g. once `session.commit()` expires the object and a later
    attribute access reloads it). Every timestamp this module ever writes
    is UTC (see `utcnow()`), so a naive value read back is always UTC,
    never local time or an unknown zone — this only ever adds the tzinfo
    a value logically already had, matching the same normalization
    `job_agent.jobs.freshness`/`job_agent.jobs.sources.greenhouse` already
    apply to their own DB-sourced timestamps."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def compute_answer_fingerprint(answers: list[GeneratedAnswer]) -> str:
    """Deterministic hash of the exact (question, answer) pairs a human is
    approving. Sorted so persistence/iteration order never changes the
    fingerprint, but any real change to a question's text or its answer
    does — re-running `applications prepare` and getting even one
    different answer invalidates every approval bound to the old set."""
    parts = sorted(f"{answer.question}=>{answer.answer or ''}" for answer in answers)
    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def create_approval(
    session: Session,
    application_id: int,
    posting_fingerprint: str,
    answer_fingerprint: str,
    *,
    ttl_hours: int = DEFAULT_APPROVAL_TTL_HOURS,
) -> ApplicationApproval:
    """Creates one new, single-use approval row. Callers (the CLI) are
    responsible for having actually shown a human everything this
    approval will authorize before calling this — this function performs
    no review of its own, it only records that one happened."""
    approval = ApplicationApproval(
        application_id=application_id,
        posting_fingerprint=posting_fingerprint,
        answer_fingerprint=answer_fingerprint,
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    session.add(approval)
    session.flush()
    return approval


def get_valid_approval(
    session: Session,
    application_id: int,
    posting_fingerprint: str,
    answer_fingerprint: str,
    *,
    now: datetime | None = None,
) -> ApplicationApproval | None:
    """Returns the most recent approval for this application that is
    unexpired, unconsumed, unrevoked, AND bound to exactly this posting
    and answer fingerprint — or `None`. A fingerprint mismatch (the
    application's current job content or current answers drifted since
    approval) is treated identically to "no approval exists" — never a
    partial match, never a fallback to an older, still-valid-looking
    approval for different content."""
    now = now or utcnow()
    rows = session.execute(
        select(ApplicationApproval)
        .where(ApplicationApproval.application_id == application_id)
        .order_by(ApplicationApproval.id.desc())
    ).scalars()
    for approval in rows:
        if approval.revoked_at is not None:
            continue
        if approval.consumed_at is not None:
            continue
        if _as_aware_utc(approval.expires_at) <= now:
            continue
        if approval.posting_fingerprint != posting_fingerprint:
            continue
        if approval.answer_fingerprint != answer_fingerprint:
            continue
        return approval
    return None


def consume_approval(
    session: Session, approval: ApplicationApproval, *, now: datetime | None = None
) -> None:
    """Marks an approval permanently spent. Callers must do this BEFORE
    attempting the real submission (fail closed on the side of "burn a
    valid approval that turned out unnecessary" rather than "leave a
    still-valid approval sitting around after an ambiguous outcome that
    might get reused") — see
    `job_agent.applications.service.submit_application`."""
    approval.consumed_at = now or utcnow()
    session.flush()


def revoke_approval(
    session: Session, approval: ApplicationApproval, *, now: datetime | None = None
) -> None:
    approval.revoked_at = now or utcnow()
    session.flush()

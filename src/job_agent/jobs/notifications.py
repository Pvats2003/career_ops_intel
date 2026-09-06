"""Notification generation — Career OS Phase 11 section 20.

Called once per `SearchRun` (see `job_agent.jobs.search_run.
execute_search_run`) against whatever jobs that run just touched. Every
notification here is grounded in data this system already computed —
a `JobMatch.overall_score`, a `WatchlistEntry` match, or a job's own
`freshness_status` — never a second, separate judgment. Never spams: a
notification is only ever created ONCE per (candidate, job, event_type)
triple — a job that stays a high match across multiple search runs does
not generate a fresh alert every run.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.db.models import Notification as NotificationRow
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.jobs.watchlist import matching_entries

HIGH_MATCH = "HIGH_MATCH"
DREAM_COMPANY = "DREAM_COMPANY"
FRESH_JOB = "FRESH_JOB"

_FRESH_STATUSES = frozenset({"JUST_POSTED", "NEW"})


def _already_notified(session: Session, candidate_id: int, job_id: int, event_type: str) -> bool:
    return (
        session.execute(
            select(NotificationRow.id).where(
                NotificationRow.candidate_id == candidate_id,
                NotificationRow.related_job_id == job_id,
                NotificationRow.event_type == event_type,
            )
        ).first()
        is not None
    )


def generate_notifications(
    session: Session,
    candidate_id: int,
    jobs_with_matches: list[tuple[JobRow, JobMatchRow | None]],
    *,
    min_score: int = 90,
) -> list[NotificationRow]:
    """Creates (and commits) any new, not-yet-sent notifications for this
    batch of jobs. Returns only the newly created rows."""
    watchlist_entries = list(
        session.execute(
            select(WatchlistEntryRow).where(WatchlistEntryRow.candidate_id == candidate_id)
        ).scalars()
    )

    created: list[NotificationRow] = []
    created_this_batch: set[tuple[int, str]] = set()
    for job, match in jobs_with_matches:
        if job.lifecycle_status != "ACTIVE":
            continue

        if (
            match is not None
            and match.overall_score >= min_score
            and (job.id, HIGH_MATCH) not in created_this_batch
            and not _already_notified(session, candidate_id, job.id, HIGH_MATCH)
        ):
            created_this_batch.add((job.id, HIGH_MATCH))
            created.append(
                NotificationRow(
                    candidate_id=candidate_id, event_type=HIGH_MATCH, channel="in_app",
                    title=f"High match: {job.title} at {job.company_name}",
                    message=(
                        f"{job.title} at {job.company_name} scored {match.overall_score}/100 "
                        "— above your notification threshold."
                    ),
                    related_job_id=job.id,
                )
            )

        hits = matching_entries(job, watchlist_entries)
        for entry in hits:
            event_type = DREAM_COMPANY if entry.kind == "COMPANY" else FRESH_JOB
            if job.freshness_status not in _FRESH_STATUSES and event_type == FRESH_JOB:
                continue
            if (job.id, event_type) in created_this_batch:
                continue
            if _already_notified(session, candidate_id, job.id, event_type):
                continue
            created_this_batch.add((job.id, event_type))
            created.append(
                NotificationRow(
                    candidate_id=candidate_id, event_type=event_type, channel="in_app",
                    title=(
                        f"Watchlist match: {job.title} at {job.company_name}"
                        if event_type == DREAM_COMPANY
                        else f"New posting: {job.title} at {job.company_name}"
                    ),
                    message=f"Matches your watchlist entry \"{entry.value}\" ({entry.kind}).",
                    related_job_id=job.id,
                )
            )

    if created:
        session.add_all(created)
        session.commit()
    return created

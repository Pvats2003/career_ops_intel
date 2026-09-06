"""Source Health + scheduler status — Career OS FINAL GOD MODE Part
6.17/6.19. Read-only views over data `job_agent.jobs.service.scan_source`
and `job_agent.jobs.scheduler` already maintain; nothing here runs a
health check or a search itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from job_agent.db.models import JobSource as JobSourceRow
from job_agent.db.models import SearchPreferences as SearchPreferencesRow
from job_agent.db.models import SearchRun as SearchRunRow
from job_agent.jobs.source_health import summarize_source_health
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.schemas import SchedulerStatusOut, SourceHealthOut

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/health", response_model=list[SourceHealthOut])
def source_health(session: SessionDep) -> list[SourceHealthOut]:
    sources = session.execute(select(JobSourceRow).order_by(JobSourceRow.name)).scalars()
    out = []
    for source in sources:
        summary = summarize_source_health(source)
        out.append(
            SourceHealthOut(
                name=source.name,
                kind=source.kind,
                enabled=source.enabled,
                status=summary.status,
                last_error=summary.last_error,
                suggested_action=summary.suggested_action,
                last_success_at=summary.last_success_at,
                last_checked_at=summary.last_checked_at,
            )
        )
    return out


@router.get("/scheduler-status", response_model=SchedulerStatusOut)
def scheduler_status(session: SessionDep, candidate: CandidateDep) -> SchedulerStatusOut:
    """Part 6.17 — the exact same due/frequency logic `job_agent.jobs.
    scheduler._is_due` uses, surfaced read-only so a candidate can see
    when their next autonomous search will actually run. This endpoint
    never starts or verifies a running scheduler thread — `job-agent
    serve` either has one polling on this same frequency or was started
    with `--no-scheduler`, which is a deployment choice outside the web
    API's visibility."""
    _, candidate_id = candidate
    preferences = session.execute(
        select(SearchPreferencesRow).where(SearchPreferencesRow.candidate_id == candidate_id)
    ).scalar_one_or_none()
    frequency_hours = preferences.search_frequency_hours if preferences is not None else 24

    last_run = session.execute(
        select(SearchRunRow)
        .where(SearchRunRow.status.in_(("COMPLETED", "PARTIAL")))
        .order_by(SearchRunRow.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_run_completed_at = last_run.completed_at if last_run else None
    next_run_due_at = None
    if last_run_completed_at is not None:
        completed_at = last_run_completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        next_run_due_at = completed_at + timedelta(hours=frequency_hours)
    else:
        next_run_due_at = datetime.now(UTC)

    return SchedulerStatusOut(
        frequency_hours=frequency_hours,
        last_run_completed_at=last_run_completed_at,
        next_run_due_at=next_run_due_at,
    )

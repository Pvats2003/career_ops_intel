"""Watchlist CRUD — Career OS Phase 11 section 19. Pure storage-layer
plumbing over `WatchlistEntry`; the actual job-matching logic lives in
`job_agent.jobs.watchlist` and is used wherever a job needs to be checked
against the candidate's watchlist (e.g. the daily briefing/notifications
in Phase 11 section 20), never duplicated here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from job_agent.db.models import Job as JobRow
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.jobs.watchlist_summary import summarize_watchlist
from job_agent.web import job_view
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.schemas import (
    WATCHLIST_KINDS,
    WatchlistEntryIn,
    WatchlistEntryOut,
    WatchlistEntrySummaryOut,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _out(row: WatchlistEntryRow) -> WatchlistEntryOut:
    return WatchlistEntryOut(id=row.id, kind=row.kind, value=row.value, created_at=row.created_at)


@router.get("", response_model=list[WatchlistEntryOut])
def list_watchlist(session: SessionDep, candidate: CandidateDep) -> list[WatchlistEntryOut]:
    _, candidate_id = candidate
    rows = session.execute(
        select(WatchlistEntryRow)
        .where(WatchlistEntryRow.candidate_id == candidate_id)
        .order_by(WatchlistEntryRow.created_at.desc())
    ).scalars()
    return [_out(r) for r in rows]


@router.get("/summary", response_model=list[WatchlistEntrySummaryOut])
def watchlist_summary(
    session: SessionDep, candidate: CandidateDep
) -> list[WatchlistEntrySummaryOut]:
    """Part 5.16's Company Watchlist view — per entry, how many ACTIVE
    postings match it, how many are new in the last 7 days, the highest
    match score among them, and the latest posting date.

    Whole-application performance forensic audit finding: this used to be
    an unfiltered `select(JobRow)` (every job ever discovered, every
    column) followed by one unbatched `latest_match()` query per job.
    `summarize_watchlist()` immediately discards every non-ACTIVE job
    itself (`active_pairs = [... if j.lifecycle_status == "ACTIVE"]`), so
    a SQL-level `lifecycle_status == "ACTIVE"` filter here changes nothing
    about the result — it just stops fetching rows that were always
    thrown away. Column projection (see `job_view.JOB_SERIALIZATION_
    COLUMNS`'s docstring) removes the large TEXT/JSON columns neither this
    function nor `summarize_watchlist()`/`matches_entry()` read. The match
    lookup is batched into one query for every ACTIVE job instead of one
    per job."""
    _, candidate_id = candidate
    entries = list(
        session.execute(
            select(WatchlistEntryRow)
            .where(WatchlistEntryRow.candidate_id == candidate_id)
            .order_by(WatchlistEntryRow.created_at.desc())
        ).scalars()
    )
    jobs = list(
        session.execute(
            select(JobRow)
            .where(JobRow.lifecycle_status == "ACTIVE")
            .options(job_view.JOB_SERIALIZATION_COLUMNS)
        ).scalars()
    )
    matches_by_job = job_view.latest_matches_by_job(session, [j.id for j in jobs], candidate_id)
    jobs_with_matches = [(j, matches_by_job.get(j.id)) for j in jobs]

    summaries = summarize_watchlist(entries, jobs_with_matches)
    return [
        WatchlistEntrySummaryOut(
            entry=_out(s.entry),
            matching_count=s.matching_count,
            new_matching_count=s.new_matching_count,
            highest_match_score=s.highest_match_score,
            latest_posted_at=s.latest_posted_at,
        )
        for s in summaries
    ]


@router.post("", response_model=WatchlistEntryOut)
def add_watchlist_entry(
    payload: WatchlistEntryIn, session: SessionDep, candidate: CandidateDep
) -> WatchlistEntryOut:
    if payload.kind not in WATCHLIST_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind must be one of {WATCHLIST_KINDS}, got {payload.kind!r}.",
        )
    value = payload.value.strip()
    if not value:
        raise HTTPException(status_code=422, detail="value must not be empty.")

    _, candidate_id = candidate
    existing = session.execute(
        select(WatchlistEntryRow).where(
            WatchlistEntryRow.candidate_id == candidate_id,
            WatchlistEntryRow.kind == payload.kind,
            WatchlistEntryRow.value == value,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _out(existing)

    row = WatchlistEntryRow(candidate_id=candidate_id, kind=payload.kind, value=value)
    session.add(row)
    session.commit()
    return _out(row)


@router.delete("/{entry_id}", status_code=204)
def delete_watchlist_entry(entry_id: int, session: SessionDep, candidate: CandidateDep) -> None:
    _, candidate_id = candidate
    row = session.get(WatchlistEntryRow, entry_id)
    if row is None or row.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail=f"No watchlist entry with id {entry_id}.")
    session.delete(row)
    session.commit()

"""Watchlist CRUD — Career OS Phase 11 section 19. Pure storage-layer
plumbing over `WatchlistEntry`; the actual job-matching logic lives in
`job_agent.jobs.watchlist` and is used wherever a job needs to be checked
against the candidate's watchlist (e.g. the daily briefing/notifications
in Phase 11 section 20), never duplicated here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.schemas import WATCHLIST_KINDS, WatchlistEntryIn, WatchlistEntryOut

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

"""Notifications API — Career OS Phase 11 section 20. Read-side plumbing
plus mark-as-read; notification GENERATION happens in `job_agent.jobs.
notifications.generate_notifications`, called from every `SearchRun`
(see `job_agent.jobs.search_run.execute_search_run`) — never duplicated
here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from job_agent.db.models import Notification as NotificationRow
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _out(row: NotificationRow) -> NotificationOut:
    return NotificationOut(
        id=row.id, event_type=row.event_type, title=row.title, message=row.message,
        related_job_id=row.related_job_id, related_application_id=row.related_application_id,
        read_at=row.read_at, created_at=row.created_at,
    )


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    session: SessionDep,
    candidate: CandidateDep,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationOut]:
    _, candidate_id = candidate
    query = (
        select(NotificationRow)
        .where(NotificationRow.candidate_id == candidate_id)
        .order_by(NotificationRow.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        query = query.where(NotificationRow.read_at.is_(None))
    rows = session.execute(query).scalars()
    return [_out(r) for r in rows]


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int, session: SessionDep, candidate: CandidateDep
) -> NotificationOut:
    _, candidate_id = candidate
    row = session.get(NotificationRow, notification_id)
    if row is None or row.candidate_id != candidate_id:
        raise HTTPException(
            status_code=404, detail=f"No notification with id {notification_id}."
        )
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        session.commit()
    return _out(row)

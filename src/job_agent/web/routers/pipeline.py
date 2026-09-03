"""The recruiting-pipeline tracker (Kanban) — section 13. Operates
entirely on `Application.pipeline_stage` (see that column's docstring in
`job_agent.db.models`), never on `Application.status`/the safety-gated
automation state machine — moving a card here is a human recording their
own real-world progress, not authorizing or performing any automated
action.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.db.models import Application, ApplicationEvent
from job_agent.db.models import Job as JobRow
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.routers.jobs import _job_out, _latest_match
from job_agent.web.schemas import (
    PIPELINE_STAGES,
    AnalyticsOut,
    CareerPathAnalyticsOut,
    PipelineItemOut,
    PipelineUpdateIn,
    StageBreakdownOut,
)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _item_out(
    session: Session, application: Application, job: JobRow, candidate_id: int
) -> PipelineItemOut:
    match_row = _latest_match(session, job.id, candidate_id)
    return PipelineItemOut(
        application_id=application.id,
        job=_job_out(job, match_row, application),
        pipeline_stage=application.pipeline_stage,
        status=application.status,
        notes=application.notes,
        recruiter_contact=application.recruiter_contact,
        interview_date=application.interview_date,
        follow_up_date=application.follow_up_date,
        outcome=application.outcome,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


@router.get("", response_model=list[PipelineItemOut])
def list_pipeline(session: SessionDep, candidate: CandidateDep) -> list[PipelineItemOut]:
    _, candidate_id = candidate
    applications = list(
        session.execute(
            select(Application).where(Application.candidate_id == candidate_id)
        ).scalars()
    )
    items = []
    for application in applications:
        job = session.get(JobRow, application.job_id)
        if job is None:
            continue
        items.append(_item_out(session, application, job, candidate_id))
    items.sort(key=lambda i: i.updated_at, reverse=True)
    return items


@router.patch("/{application_id}", response_model=PipelineItemOut)
def update_pipeline_item(
    application_id: int, body: PipelineUpdateIn, session: SessionDep, candidate: CandidateDep
) -> PipelineItemOut:
    _, candidate_id = candidate
    application = session.get(Application, application_id)
    if application is None or application.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail=f"No application with id {application_id}.")

    if body.pipeline_stage is not None:
        if body.pipeline_stage not in PIPELINE_STAGES:
            raise HTTPException(
                status_code=422,
                detail=f"pipeline_stage must be one of {PIPELINE_STAGES}.",
            )
        application.pipeline_stage = body.pipeline_stage
    if body.notes is not None:
        application.notes = body.notes
    if body.recruiter_contact is not None:
        application.recruiter_contact = body.recruiter_contact
    if body.interview_date is not None:
        application.interview_date = body.interview_date
    if body.follow_up_date is not None:
        application.follow_up_date = body.follow_up_date
    if body.outcome is not None:
        application.outcome = body.outcome

    session.commit()
    job = session.get(JobRow, application.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Application's job no longer exists.")
    return _item_out(session, application, job, candidate_id)


@router.delete("/{application_id}", status_code=204)
def remove_pipeline_item(application_id: int, session: SessionDep, candidate: CandidateDep) -> None:
    """Un-save a job. Refuses once anything beyond SAVED/SHORTLISTED has
    happened (a real submission, an audit trail) — that history is never
    silently deleted; move it to REJECTED instead.

    The `pipeline_stage`/`submitted_at is None` guards below mean the only
    `ApplicationEvent` rows a deletable application can ever have is the
    single `APPLICATION_DISCOVERED` bookkeeping event `get_or_create_
    application` writes when "save" first creates the row — never a
    submission-related event — so removing those alongside the row here
    does not touch the safety-relevant audit trail `job_agent.
    applications.repository.record_event`'s docstring describes."""
    _, candidate_id = candidate
    application = session.get(Application, application_id)
    if application is None or application.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail=f"No application with id {application_id}.")
    if application.pipeline_stage not in ("SAVED", "SHORTLISTED"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a pipeline item once it has progressed past SHORTLISTED — "
            "move it to REJECTED instead to preserve the record.",
        )
    if application.submitted_at is not None:
        raise HTTPException(
            status_code=409, detail="Cannot delete an application that has a real submission."
        )
    events = session.execute(
        select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
    ).scalars()
    for event in events:
        session.delete(event)
    session.flush()
    session.delete(application)
    session.commit()


@router.get("/analytics", response_model=AnalyticsOut)
def pipeline_analytics(session: SessionDep, candidate: CandidateDep) -> AnalyticsOut:
    _, candidate_id = candidate
    applications = list(
        session.execute(
            select(Application).where(Application.candidate_id == candidate_id)
        ).scalars()
    )
    total_jobs_discovered = session.execute(select(JobRow)).scalars().all()

    stage_counts: dict[str, int] = {stage: 0 for stage in PIPELINE_STAGES}
    for application in applications:
        stage = application.pipeline_stage
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    applied_stages = {"APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED"}
    total_applied = sum(stage_counts.get(s, 0) for s in applied_stages)
    total_interviews = stage_counts.get("INTERVIEW", 0) + stage_counts.get("OFFER", 0)
    total_offers = stage_counts.get("OFFER", 0)
    total_rejections = stage_counts.get("REJECTED", 0)
    total_shortlisted = stage_counts.get("SHORTLISTED", 0) + total_applied

    by_company: dict[str, dict[str, int]] = {}
    for application in applications:
        job = session.get(JobRow, application.job_id)
        if job is None:
            continue
        bucket = by_company.setdefault(
            job.company_name, {"applications": 0, "interviews": 0, "offers": 0}
        )
        if application.pipeline_stage in applied_stages:
            bucket["applications"] += 1
        if application.pipeline_stage in ("INTERVIEW", "OFFER"):
            bucket["interviews"] += 1
        if application.pipeline_stage == "OFFER":
            bucket["offers"] += 1

    company_stats = [
        CareerPathAnalyticsOut(
            label=name,
            applications=stats["applications"],
            interviews=stats["interviews"],
            offers=stats["offers"],
            interview_rate=(
                round(100 * stats["interviews"] / stats["applications"], 1)
                if stats["applications"]
                else 0.0
            ),
        )
        for name, stats in by_company.items()
        if stats["applications"] > 0
    ]
    company_stats.sort(key=lambda c: c.interview_rate, reverse=True)

    return AnalyticsOut(
        stage_breakdown=[
            StageBreakdownOut(stage=stage, count=stage_counts.get(stage, 0))
            for stage in PIPELINE_STAGES
        ],
        total_jobs_discovered=len(total_jobs_discovered),
        total_matched=len(applications),
        total_shortlisted=total_shortlisted,
        total_applied=total_applied,
        total_interviews=total_interviews,
        total_offers=total_offers,
        total_rejections=total_rejections,
        application_rate=(
            round(100 * total_applied / len(applications), 1) if applications else 0.0
        ),
        interview_rate=(
            round(100 * total_interviews / total_applied, 1) if total_applied else 0.0
        ),
        offer_rate=(round(100 * total_offers / total_applied, 1) if total_applied else 0.0),
        by_company=company_stats,
    )

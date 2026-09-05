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

from job_agent.applications.checklist import compute_checklist
from job_agent.applications.follow_up import compute_follow_up_recommendations
from job_agent.applications.follow_up_message import generate_follow_up_message
from job_agent.applications.repository import record_event
from job_agent.applications.scorecard import compute_scorecard
from job_agent.db.models import Application, ApplicationEvent, Resume
from job_agent.db.models import Job as JobRow
from job_agent.web import job_view
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.routers.jobs import _job_out, _latest_match
from job_agent.web.schemas import (
    PIPELINE_STAGES,
    AnalyticsOut,
    ApplicationChecklistOut,
    ApplicationHistoryEventOut,
    ApplicationScorecardOut,
    CareerPathAnalyticsOut,
    FollowUpMessageOut,
    FollowUpRecommendationOut,
    PipelineItemOut,
    PipelineUpdateIn,
    StageBreakdownOut,
)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _item_out(
    session: Session, application: Application, job: JobRow, candidate_id: int
) -> PipelineItemOut:
    match_row = _latest_match(session, job.id, candidate_id)
    resume = session.get(Resume, application.resume_id) if application.resume_id else None
    scorecard = compute_scorecard(job, match_row)
    checklist = compute_checklist(application, resume)
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
        scorecard=ApplicationScorecardOut(
            candidate_fit=scorecard.candidate_fit,
            job_quality=scorecard.job_quality,
            career_value=scorecard.career_value,
            application_viability=scorecard.application_viability,
            overall_score=scorecard.overall_score,
            overall_recommendation=scorecard.overall_recommendation,
        ),
        checklist=ApplicationChecklistOut(
            resume_selected=checklist.resume_selected,
            resume_tailored=checklist.resume_tailored,
            cover_letter_ready=checklist.cover_letter_ready,
            questions_prepared=checklist.questions_prepared,
            submitted=checklist.submitted,
            confirmation_received=checklist.confirmation_received,
        ),
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
    """Every field actually changed here is also appended to
    `application_events` (Part 4.13's Application History) via
    `record_event` — an insert-only log, so re-editing a note or moving a
    card back a stage never erases what the record used to say."""
    _, candidate_id = candidate
    application = session.get(Application, application_id)
    if application is None or application.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail=f"No application with id {application_id}.")

    changes: dict[str, dict[str, str | bool | None]] = {}

    if body.pipeline_stage is not None:
        if body.pipeline_stage not in PIPELINE_STAGES:
            raise HTTPException(
                status_code=422,
                detail=f"pipeline_stage must be one of {PIPELINE_STAGES}.",
            )
        if body.pipeline_stage != application.pipeline_stage:
            changes["pipeline_stage"] = {
                "from": application.pipeline_stage,
                "to": body.pipeline_stage,
            }
            application.pipeline_stage = body.pipeline_stage
    if body.notes is not None and body.notes != application.notes:
        changes["notes"] = {"to": body.notes}
        application.notes = body.notes
    recruiter_contact_changed = (
        body.recruiter_contact is not None
        and body.recruiter_contact != application.recruiter_contact
    )
    if recruiter_contact_changed:
        changes["recruiter_contact"] = {"to": body.recruiter_contact}
        application.recruiter_contact = body.recruiter_contact
    if body.interview_date is not None:
        application.interview_date = body.interview_date
    if body.follow_up_date is not None:
        application.follow_up_date = body.follow_up_date
    if body.outcome is not None and body.outcome != application.outcome:
        changes["outcome"] = {"from": application.outcome, "to": body.outcome}
        application.outcome = body.outcome
    cover_letter_ready_changed = (
        body.cover_letter_ready is not None
        and body.cover_letter_ready != application.cover_letter_ready
    )
    if cover_letter_ready_changed:
        changes["cover_letter_ready"] = {"to": body.cover_letter_ready}
        application.cover_letter_ready = body.cover_letter_ready
    questions_prepared_changed = (
        body.questions_prepared is not None
        and body.questions_prepared != application.questions_prepared
    )
    if questions_prepared_changed:
        changes["questions_prepared"] = {"to": body.questions_prepared}
        application.questions_prepared = body.questions_prepared

    if changes:
        record_event(session, application.id, "PIPELINE_UPDATED", changes)
    session.commit()
    job = session.get(JobRow, application.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Application's job no longer exists.")
    return _item_out(session, application, job, candidate_id)


@router.get("/{application_id}/history", response_model=list[ApplicationHistoryEventOut])
def application_history(
    application_id: int, session: SessionDep, candidate: CandidateDep
) -> list[ApplicationHistoryEventOut]:
    """Part 4.13's Application History — the same immutable
    `application_events` audit trail the automation pipeline already
    writes to, read back oldest-first. Nothing here is ever edited or
    deleted; a correction is a new event, not a rewrite."""
    _, candidate_id = candidate
    application = session.get(Application, application_id)
    if application is None or application.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail=f"No application with id {application_id}.")
    events = session.execute(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.created_at)
    ).scalars()
    return [
        ApplicationHistoryEventOut(
            event_type=e.event_type, details=e.details, created_at=e.created_at
        )
        for e in events
    ]


@router.delete("/{application_id}", status_code=204)
def remove_pipeline_item(application_id: int, session: SessionDep, candidate: CandidateDep) -> None:
    """Un-save a job. Refuses once anything beyond SAVED/SHORTLISTED has
    happened (a real submission, an audit trail) — that history is never
    silently deleted; move it to REJECTED instead.

    The `pipeline_stage`/`submitted_at is None` guards below mean a
    deletable application can only ever carry the initial
    `APPLICATION_DISCOVERED` bookkeeping event plus any `PIPELINE_UPDATED`
    events from editing notes/recruiter contact while still SAVED/
    SHORTLISTED — never a submission-related event — so removing those
    alongside the row here does not touch the safety-relevant audit trail
    `job_agent.applications.repository.record_event`'s docstring
    describes."""
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


@router.get("/follow-ups", response_model=list[FollowUpRecommendationOut])
def follow_up_recommendations(
    session: SessionDep, candidate: CandidateDep
) -> list[FollowUpRecommendationOut]:
    """Phase 13 — applications sitting in an active waiting stage
    (APPLIED/ASSESSMENT/INTERVIEW) with no stage change in 7+ days.
    Never contacts a recruiter — this only flags what to look at, and
    (Part 4.14) drafts the actual message text for the candidate to
    review and send themselves; nothing here is ever sent automatically."""
    profile, candidate_id = candidate
    applications = list(
        session.execute(
            select(Application).where(Application.candidate_id == candidate_id)
        ).scalars()
    )
    # Dashboard performance forensic fix: this used to call
    # `session.get(JobRow, application.job_id)` once per application (an
    # unbounded N+1 that grows with the candidate's whole application
    # history, not just today's page) and `_latest_match()` once per
    # follow-up-eligible recommendation. Both batched into one query each.
    jobs_by_id = {
        job.id: job
        for job in session.execute(
            select(JobRow).where(JobRow.id.in_([a.job_id for a in applications]))
        ).scalars()
    }
    applications_with_jobs = [
        (application, jobs_by_id[application.job_id])
        for application in applications
        if application.job_id in jobs_by_id
    ]

    recommendations = compute_follow_up_recommendations(applications_with_jobs)
    matches_by_job = job_view.latest_matches_by_job(
        session, [r.job.id for r in recommendations], candidate_id
    )
    candidate_name = profile.identity_name.value or "your name"
    results = []
    for r in recommendations:
        message = generate_follow_up_message(r, candidate_name)
        results.append(
            FollowUpRecommendationOut(
                application_id=r.application.id,
                job=_job_out(r.job, matches_by_job.get(r.job.id), r.application),
                applied_days_ago=r.applied_days_ago,
                suggested_action=r.suggested_action,
                message=FollowUpMessageOut(subject=message.subject, body=message.body),
            )
        )
    return results


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
        interview_rate=(round(100 * total_interviews / total_applied, 1) if total_applied else 0.0),
        offer_rate=(round(100 * total_offers / total_applied, 1) if total_applied else 0.0),
        by_company=company_stats,
    )

"""Section 10 — the one screen that should answer "what are the best jobs
I should apply to right now" within seconds. Pure read aggregation over
`jobs`/`job_matches`/`applications` and the current resume validation
status; triggers no scan/match itself (the dashboard's "Scan for jobs" /
"Re-run matching" actions call `job_agent.web.routers.jobs`'s endpoints).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.resume.repository import get_latest_version
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.routers.jobs import _application_for, _job_out, _latest_match
from job_agent.web.schemas import DashboardSummaryOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_APPLY_PRIORITY_DECISIONS = {"APPLY"}
_APPLIED_STAGES = {"APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED"}


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(session: SessionDep, candidate: CandidateDep) -> DashboardSummaryOut:
    _, candidate_id = candidate
    jobs = list(session.execute(select(JobRow)).scalars())
    applications = list(
        session.execute(
            select(Application).where(Application.candidate_id == candidate_id)
        ).scalars()
    )

    version = get_latest_version(session, candidate_id)

    scored: list[tuple[JobRow, JobMatch]] = []
    apply_priority_count = 0
    for job in jobs:
        match_row = _latest_match(session, job.id, candidate_id)
        if match_row is not None:
            scored.append((job, match_row))
            if match_row.decision in _APPLY_PRIORITY_DECISIONS:
                apply_priority_count += 1

    scored.sort(key=lambda pair: pair[1].overall_score, reverse=True)
    top = scored[:10]
    top_out = [
        _job_out(job, match_row, _application_for(session, job.id, candidate_id))
        for job, match_row in top
    ]

    shortlisted = sum(
        1 for a in applications if a.pipeline_stage in ("SHORTLISTED", *_APPLIED_STAGES)
    )
    applied = sum(1 for a in applications if a.pipeline_stage in _APPLIED_STAGES)
    interviewing = sum(1 for a in applications if a.pipeline_stage in ("INTERVIEW", "OFFER"))
    offers = sum(1 for a in applications if a.pipeline_stage == "OFFER")

    return DashboardSummaryOut(
        resume_parsed=True,
        resume_validation_status=version.validation_status if version else None,
        job_matches=len(scored),
        shortlisted=shortlisted,
        applied=applied,
        interviewing=interviewing,
        offers=offers,
        total_jobs_discovered=len(jobs),
        apply_priority_count=apply_priority_count,
        top_opportunities=top_out,
    )

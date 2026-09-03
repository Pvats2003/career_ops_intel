"""Job discovery, matching, listing, and the "save a job" action.

Every write here goes through the exact same `job_agent.jobs.service`/
`job_agent.matching.service`/`job_agent.applications.repository`
functions the CLI (`jobs scan`, `jobs match`, `applications prepare`)
already uses — this module only adds HTTP plumbing and read-side
filtering/sorting on top of the `jobs`/`job_matches`/`applications`
tables those services already populate. No job is ever fabricated: a
fresh install with no source enabled in `config/sources.yaml` returns an
empty list, honestly, rather than seeded/demo data.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.applications.repository import get_or_create_application
from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.jobs.schema import FreshnessStatus
from job_agent.jobs.service import build_sources, run_scan
from job_agent.llm.provider import build_llm_provider
from job_agent.matching.service import run_matching
from job_agent.net.http_client import ResilientHttpClient
from job_agent.web.deps import CandidateDep, ConfigDep, SessionDep
from job_agent.web.schemas import (
    JobDetailOut,
    JobListOut,
    JobOut,
    MatchOut,
    MatchRunOut,
    ScanRunOut,
    ScanSourceResultOut,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_FRESHNESS_LABELS: dict[str, str] = {
    FreshnessStatus.JUST_POSTED.value: "Posted within hours",
    FreshnessStatus.NEW.value: "Posted today",
    FreshnessStatus.RECENT.value: "Posted recently",
    FreshnessStatus.OLD.value: "Posted a while ago",
    FreshnessStatus.UNKNOWN_POST_DATE.value: "Posted date unknown",
}


def _latest_match(session: Session, job_id: int, candidate_id: int) -> JobMatch | None:
    return session.execute(
        select(JobMatch)
        .where(JobMatch.job_id == job_id, JobMatch.candidate_id == candidate_id)
        .order_by(JobMatch.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _application_for(session: Session, job_id: int, candidate_id: int) -> Application | None:
    return session.execute(
        select(Application).where(
            Application.job_id == job_id, Application.candidate_id == candidate_id
        )
    ).scalar_one_or_none()


def _match_out(row: JobMatch | None) -> MatchOut | None:
    if row is None:
        return None
    return MatchOut(
        overall_score=int(row.overall_score),
        decision=row.decision,
        skills_match=int(row.skills_match or 0),
        experience_match=int(row.experience_match or 0),
        role_match=int(row.role_match or 0),
        project_match=int(row.project_match or 0),
        education_match=int(row.education_match or 0),
        location_match=int(row.location_match or 0),
        seniority_match=int(row.seniority_match or 0),
        eligibility_match=int(row.eligibility_match or 0),
        missing_requirements=list(row.missing_requirements or []),
        concerns=list(row.concerns or []),
        hard_stop_reasons=list(row.hard_stop_reasons or []),
        excluded_reasons=list(row.excluded_reasons or []),
        reasoning=row.reasoning or "",
        semantic_available=bool(row.semantic_available),
    )


def _job_out(
    job: JobRow, match_row: JobMatch | None, application: Application | None
) -> JobOut:
    return JobOut(
        id=job.id,
        title=job.title,
        company_name=job.company_name,
        location=job.location,
        remote_type=job.remote_type,
        employment_type=job.employment_type,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        currency=job.currency,
        application_url=job.application_url,
        posted_at=job.posted_at,
        discovered_at=job.discovered_at,
        freshness_status=job.freshness_status,
        freshness_label=_FRESHNESS_LABELS.get(job.freshness_status, job.freshness_status),
        source_name=None,
        match=_match_out(match_row),
        pipeline_stage=application.pipeline_stage if application else None,
        application_id=application.id if application else None,
    )


@router.get("", response_model=JobListOut)
def list_jobs(
    session: SessionDep,
    candidate: CandidateDep,
    min_score: int | None = Query(default=None, ge=0, le=100),
    decision: str | None = Query(default=None),
    remote_type: str | None = Query(default=None),
    location: str | None = Query(default=None),
    company: str | None = Query(default=None),
    min_salary: float | None = Query(default=None),
    pipeline_stage: str | None = Query(default=None),
    sort: Literal["match", "newest", "salary", "company"] = Query(default="match"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    _, candidate_id = candidate
    jobs = list(session.execute(select(JobRow)).scalars())

    items: list[JobOut] = []
    for job in jobs:
        match_row = _latest_match(session, job.id, candidate_id)
        application = _application_for(session, job.id, candidate_id)

        if decision is not None and (match_row is None or match_row.decision != decision):
            continue
        if min_score is not None and (match_row is None or match_row.overall_score < min_score):
            continue
        if remote_type is not None and (job.remote_type or "").lower() != remote_type.lower():
            continue
        if location is not None and location.lower() not in (job.location or "").lower():
            continue
        if company is not None and company.lower() not in job.company_name.lower():
            continue
        if min_salary is not None and (job.salary_max or job.salary_min or 0) < min_salary:
            continue
        if pipeline_stage is not None and (
            application is None or application.pipeline_stage != pipeline_stage
        ):
            continue

        items.append(_job_out(job, match_row, application))

    if sort == "match":
        items.sort(key=lambda j: (j.match.overall_score if j.match else -1), reverse=True)
    elif sort == "newest":
        items.sort(key=lambda j: j.posted_at or j.discovered_at, reverse=True)
    elif sort == "salary":
        items.sort(key=lambda j: (j.salary_max or j.salary_min or 0), reverse=True)
    elif sort == "company":
        items.sort(key=lambda j: j.company_name.lower())

    total = len(items)
    page = items[offset : offset + limit]
    return JobListOut(total=total, items=page)


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, session: SessionDep, candidate: CandidateDep) -> JobDetailOut:
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    _, candidate_id = candidate
    match_row = _latest_match(session, job.id, candidate_id)
    application = _application_for(session, job.id, candidate_id)
    base = _job_out(job, match_row, application)
    return JobDetailOut(
        **base.model_dump(),
        description=job.description,
        requirements=job.requirements,
        preferred_qualifications=job.preferred_qualifications,
        visa_information=job.visa_information,
        company_url=job.company_url,
    )


@router.post("/{job_id}/save", response_model=JobDetailOut)
def save_job(
    job_id: int, session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> JobDetailOut:
    """Bookmark a job into the recruiting pipeline at SAVED — a no-op if
    it's already further along (never regresses an existing pipeline_stage
    back to SAVED)."""
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    _, candidate_id = candidate
    application, _created = get_or_create_application(
        session, job.id, candidate_id, dry_run=config.dry_run
    )
    session.commit()
    match_row = _latest_match(session, job.id, candidate_id)
    base = _job_out(job, match_row, application)
    return JobDetailOut(
        **base.model_dump(),
        description=job.description,
        requirements=job.requirements,
        preferred_qualifications=job.preferred_qualifications,
        visa_information=job.visa_information,
        company_url=job.company_url,
    )


@router.post("/scan", response_model=ScanRunOut)
def scan_jobs(session: SessionDep, config: ConfigDep) -> ScanRunOut:
    """Runs the same `job_agent.jobs.service.run_scan` the `jobs scan` CLI
    command runs. Honest by construction: if no source is enabled in
    `config/sources.yaml`, `build_sources` returns an empty list and this
    reports zero results rather than inventing any."""
    http = ResilientHttpClient()
    try:
        enabled = build_sources(config, http)
    finally:
        http.close()
    results = run_scan(session, config)
    return ScanRunOut(
        results=[
            ScanSourceResultOut(
                source_name=r.source_name,
                identifier=r.identifier,
                fetched=r.fetched,
                created=r.created,
                updated=r.updated,
                errors=r.errors,
            )
            for r in results
        ],
        enabled_sources=len(enabled),
    )


@router.post("/match", response_model=MatchRunOut)
def match_jobs(session: SessionDep, candidate: CandidateDep, config: ConfigDep) -> MatchRunOut:
    """Runs `job_agent.matching.service.run_matching` against every job
    currently in the database — the same operation `jobs match` performs
    from the CLI. Uses the LLM provider only if `ANTHROPIC_API_KEY` is
    configured; otherwise falls back to the deterministic-only matcher,
    exactly like the CLI does."""
    profile, candidate_id = candidate
    llm = build_llm_provider(config)
    outcomes = run_matching(session, config, profile, candidate_id, llm=llm)
    counts = {"APPLY": 0, "REVIEW": 0, "SAVE": 0, "SKIP": 0, "HUMAN_REQUIRED": 0}
    for outcome in outcomes:
        counts[outcome.result.decision.value] = counts.get(outcome.result.decision.value, 0) + 1
    return MatchRunOut(
        matched=len(outcomes),
        apply_count=counts.get("APPLY", 0),
        review_count=counts.get("REVIEW", 0),
        save_count=counts.get("SAVE", 0),
        skip_count=counts.get("SKIP", 0),
        human_required_count=counts.get("HUMAN_REQUIRED", 0),
    )

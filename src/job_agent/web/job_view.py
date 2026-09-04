"""Shared read-side helpers for turning DB rows into `JobOut`/`MatchOut` —
used by both `web/routers/jobs.py` and `web/routers/companies.py` so the
two never grow two separate, drifting serializations of the same job row.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.jobs.schema import FreshnessStatus
from job_agent.web.schemas import JobOut, MatchOut

FRESHNESS_LABELS: dict[str, str] = {
    FreshnessStatus.JUST_POSTED.value: "Posted within hours",
    FreshnessStatus.NEW.value: "Posted today",
    FreshnessStatus.RECENT.value: "Posted recently",
    FreshnessStatus.OLD.value: "Posted a while ago",
    FreshnessStatus.UNKNOWN_POST_DATE.value: "Posted date unknown",
}


def latest_match(session: Session, job_id: int, candidate_id: int) -> JobMatch | None:
    return session.execute(
        select(JobMatch)
        .where(JobMatch.job_id == job_id, JobMatch.candidate_id == candidate_id)
        .order_by(JobMatch.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def application_for(session: Session, job_id: int, candidate_id: int) -> Application | None:
    return session.execute(
        select(Application).where(
            Application.job_id == job_id, Application.candidate_id == candidate_id
        )
    ).scalar_one_or_none()


def matched_jobs_with_applications(
    session: Session, candidate_id: int
) -> list[tuple[JobRow, Application | None]]:
    """Every job this candidate has been MATCHED against (i.e. actually
    shown a score for), paired with their `Application` row if they
    engaged with it (save/shortlist/apply — anything), else `None`. The
    one shared "what has this candidate seen and what did they do about
    it" query — used by both behavioral insights (`web/routers/
    candidate.py`) and the ranking engine's behavioral-fit signal
    (`job_agent.matching.ranking`), so the two never compute this from
    two different, potentially-drifting queries."""
    matched_job_ids = list(
        session.execute(
            select(JobMatch.job_id).where(JobMatch.candidate_id == candidate_id).distinct()
        ).scalars()
    )
    pairs: list[tuple[JobRow, Application | None]] = []
    for job_id in matched_job_ids:
        job = session.get(JobRow, job_id)
        if job is None:
            continue
        pairs.append((job, application_for(session, job_id, candidate_id)))
    return pairs


def match_out(row: JobMatch | None) -> MatchOut | None:
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


def job_out(
    job: JobRow,
    match_row: JobMatch | None,
    application: Application | None,
    *,
    source_name: str | None = None,
    also_seen_on: list[str] | None = None,
    duplicate_count: int = 0,
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
        freshness_label=FRESHNESS_LABELS.get(job.freshness_status, job.freshness_status),
        source_name=source_name,
        match=match_out(match_row),
        pipeline_stage=application.pipeline_stage if application else None,
        application_id=application.id if application else None,
        lifecycle_status=job.lifecycle_status,
        also_seen_on=also_seen_on or [],
        duplicate_count=duplicate_count,
    )

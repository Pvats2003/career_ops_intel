"""Shared read-side helpers for turning DB rows into `JobOut`/`MatchOut` —
used by both `web/routers/jobs.py` and `web/routers/companies.py` so the
two never grow two separate, drifting serializations of the same job row.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.jobs.confidence import assess_data_confidence
from job_agent.jobs.schema import FreshnessStatus
from job_agent.jobs.viability import assess_application_viability
from job_agent.web.schemas import ApplicationViabilityOut, DataConfidenceOut, JobOut, MatchOut

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


def latest_matches_by_job(
    session: Session, job_ids: list[int], candidate_id: int
) -> dict[int, JobMatch]:
    """The same "latest match per job" `latest_match()` computes, batched
    into one query instead of one-per-job — production-audit finding: a
    dashboard covering N jobs called `latest_match()` once per job (an
    unbounded N+1 query pattern that only gets worse as more jobs are
    discovered, and on Neon's free tier each extra round-trip carries real
    network latency, not just local-disk-cache overhead like SQLite in
    tests). Only used where every job's match is needed at once
    (`dashboard_summary()`); call sites that only ever need ONE job's
    match (job detail, a single row) still use `latest_match()` — a
    single extra query per real page view is not the problem this fixes."""
    if not job_ids:
        return {}
    latest_per_job = (
        select(JobMatch.job_id, func.max(JobMatch.created_at).label("max_created_at"))
        .where(JobMatch.candidate_id == candidate_id, JobMatch.job_id.in_(job_ids))
        .group_by(JobMatch.job_id)
        .subquery()
    )
    rows = session.execute(
        select(JobMatch).join(
            latest_per_job,
            (JobMatch.job_id == latest_per_job.c.job_id)
            & (JobMatch.created_at == latest_per_job.c.max_created_at),
        )
    ).scalars()
    return {row.job_id: row for row in rows}


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
    confidence = assess_data_confidence(job)
    viability = assess_application_viability(job, match_row)
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
        data_confidence=DataConfidenceOut(level=confidence.level, reasons=confidence.reasons),
        viability=ApplicationViabilityOut(
            url_exists=viability.url_exists,
            direct_application=viability.direct_application,
            job_active=viability.job_active,
            qualifications_status=viability.qualifications_status,
            location_compatible=viability.location_compatible,
            visa_info_available=viability.visa_info_available,
            overall=viability.overall,
            reasons=viability.reasons,
        ),
    )

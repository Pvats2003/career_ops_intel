"""Company intelligence — Career OS Phase 10.

There is no dedicated `Company` table: every fact here is derived, live,
by aggregating the `Job` rows this system has actually discovered for a
given company. That is deliberate — anything this system hasn't verified
(funding stage, headcount, culture, "About" copy) stays `None`/unknown
rather than fabricated. `industry`, `size`, `career_page_url`, and `notes`
are always `None` today because nothing upstream currently populates
them; they're modeled so a future, real data source can fill them in
without a schema change, never as placeholders standing in for a guess.

A company's `id` is the smallest `Job.id` among its postings — stable for
as long as that job row exists, and never a fabricated/hashed identifier.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.matching.company_fit import compute_company_fit
from job_agent.web import job_view
from job_agent.web.deps import CandidateDep, SessionDep
from job_agent.web.schemas import CompanyOut

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _group_jobs_by_company(jobs: list[JobRow]) -> dict[str, list[JobRow]]:
    groups: dict[str, list[JobRow]] = {}
    for job in jobs:
        groups.setdefault(job.company_name, []).append(job)
    return groups


def _company_out(
    session: Session,
    company_name: str,
    jobs: list[JobRow],
    candidate_id: int,
    matches_by_job: dict[int, JobMatch] | None = None,
    applications_by_job: dict[int, Application] | None = None,
) -> CompanyOut:
    """`matches_by_job`/`applications_by_job` let a caller iterating many
    companies at once (`list_companies`) batch these lookups ONCE across
    every job in every company, instead of this function re-querying per
    job. `get_company()` (a single company's jobs) still passes `None` for
    both, in which case this batches internally, scoped to just this
    company's jobs — still one query each instead of one-per-job.

    Production-audit finding (whole-application forensic audit): this used
    to call `latest_match()` per job for the company-fit computation, then
    call it AGAIN plus `application_for()` per job while building
    `matching_jobs` — up to 3 unbatched queries per job, the single most
    expensive N+1 found across the whole app. Batched into at most 2
    queries total per call regardless of job count, with the exact same
    "most recent match"/"application for this job, if any" semantics."""
    company_id = min(j.id for j in jobs)
    website = next((j.company_url for j in jobs if j.company_url), None)
    open_roles = sum(1 for j in jobs if j.lifecycle_status == "ACTIVE")

    if matches_by_job is None:
        matches_by_job = job_view.latest_matches_by_job(
            session, [j.id for j in jobs], candidate_id
        )
    if applications_by_job is None:
        applications_by_job = job_view.applications_by_job(
            session, [j.id for j in jobs], candidate_id
        )

    matches = [m for j in jobs if (m := matches_by_job.get(j.id)) is not None]
    fit_score, fit_reasons = compute_company_fit(matches)

    matching_jobs = [
        job_view.job_out(
            j, matches_by_job.get(j.id), applications_by_job.get(j.id)
        )
        for j in sorted(jobs, key=lambda j: j.posted_at or j.discovered_at, reverse=True)
    ]

    active_matched = [j for j in matching_jobs if j.lifecycle_status == "ACTIVE" and j.match]
    best_role = (
        max(active_matched, key=lambda j: j.match.overall_score) if active_matched else None
    )

    return CompanyOut(
        id=company_id,
        name=company_name,
        industry=None,
        size=None,
        website=website,
        career_page_url=None,
        notes=None,
        open_roles=open_roles,
        matching_jobs=matching_jobs,
        best_role=best_role,
        company_fit=fit_score,
        company_fit_reasons=list(fit_reasons),
    )


@router.get("", response_model=list[CompanyOut])
def list_companies(session: SessionDep, candidate: CandidateDep) -> list[CompanyOut]:
    """Every company with at least one discovered job posting, most open
    roles first. Honest by construction: a fresh install with no jobs
    scanned yet returns an empty list."""
    _, candidate_id = candidate
    # Whole-application performance forensic audit finding: this used to be
    # `select(JobRow)` with no column projection, pulling every large TEXT/
    # JSON field (description/requirements/raw_data/...) for every job in
    # the table just to compute a company summary card. None of
    # `_company_out()`'s output touches those fields (traced field-by-
    # field into `job_out()`/`assess_data_confidence()`/`assess_
    # application_viability()` — see `job_view.JOB_SERIALIZATION_COLUMNS`'s
    # docstring); Companies intentionally still shows a company's FULL
    # posting history (open and closed alike — see `_company_out`'s
    # `matching_jobs`), so no `lifecycle_status` filter is applied here.
    jobs = list(
        session.execute(select(JobRow).options(job_view.JOB_SERIALIZATION_COLUMNS)).scalars()
    )
    job_ids = [j.id for j in jobs]
    # One batched query each for the WHOLE table's worth of jobs, instead
    # of `_company_out()` doing up to 3 unbatched queries per job.
    matches_by_job = job_view.latest_matches_by_job(session, job_ids, candidate_id)
    applications_by_job = job_view.applications_by_job(session, job_ids, candidate_id)
    groups = _group_jobs_by_company(jobs)
    companies = [
        _company_out(session, name, company_jobs, candidate_id, matches_by_job, applications_by_job)
        for name, company_jobs in groups.items()
    ]
    companies.sort(key=lambda c: c.open_roles, reverse=True)
    return companies


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, session: SessionDep, candidate: CandidateDep) -> CompanyOut:
    job = session.get(JobRow, company_id, options=[job_view.JOB_SERIALIZATION_COLUMNS])
    if job is None:
        raise HTTPException(status_code=404, detail=f"No company with id {company_id}.")
    _, candidate_id = candidate
    jobs = list(
        session.execute(
            select(JobRow)
            .where(JobRow.company_name == job.company_name)
            .options(job_view.JOB_SERIALIZATION_COLUMNS)
        ).scalars()
    )
    return _company_out(session, job.company_name, jobs, candidate_id)

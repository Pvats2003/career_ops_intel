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
    session: Session, company_name: str, jobs: list[JobRow], candidate_id: int
) -> CompanyOut:
    company_id = min(j.id for j in jobs)
    website = next((j.company_url for j in jobs if j.company_url), None)
    open_roles = sum(1 for j in jobs if j.lifecycle_status == "ACTIVE")

    matches = [
        m
        for j in jobs
        if (m := job_view.latest_match(session, j.id, candidate_id)) is not None
    ]
    fit_score, fit_reasons = compute_company_fit(matches)

    matching_jobs = [
        job_view.job_out(
            j, job_view.latest_match(session, j.id, candidate_id),
            job_view.application_for(session, j.id, candidate_id),
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
    jobs = list(session.execute(select(JobRow)).scalars())
    groups = _group_jobs_by_company(jobs)
    companies = [
        _company_out(session, name, company_jobs, candidate_id)
        for name, company_jobs in groups.items()
    ]
    companies.sort(key=lambda c: c.open_roles, reverse=True)
    return companies


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, session: SessionDep, candidate: CandidateDep) -> CompanyOut:
    job = session.get(JobRow, company_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No company with id {company_id}.")
    _, candidate_id = candidate
    jobs = list(
        session.execute(select(JobRow).where(JobRow.company_name == job.company_name)).scalars()
    )
    return _company_out(session, job.company_name, jobs, candidate_id)

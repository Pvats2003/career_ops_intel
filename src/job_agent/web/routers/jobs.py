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

from job_agent.applications.answer_bank import load_answer_bank
from job_agent.applications.answer_engine import classify_question, generate_answer
from job_agent.applications.cover_letter import generate_cover_letter
from job_agent.applications.repository import get_or_create_application
from job_agent.applications.schema import ApplicationQuestion
from job_agent.candidate.learning import compute_learned_preferences
from job_agent.config.loader import AppConfig
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.db.models import JobSource as JobSourceRow
from job_agent.db.models import SearchRun as SearchRunRow
from job_agent.jobs.search_run import execute_search_run
from job_agent.jobs.service import build_sources, run_scan
from job_agent.jobs.url_check import check_application_url
from job_agent.llm.provider import build_llm_provider
from job_agent.matching.ranking import rank_jobs
from job_agent.matching.service import run_matching
from job_agent.net.http_client import ResilientHttpClient
from job_agent.resume.extractor import extract_resume_text
from job_agent.resume.tailor import tailor_resume_for_job
from job_agent.web import job_view
from job_agent.web.deps import CandidateDep, ConfigDep, SessionDep
from job_agent.web.schemas import (
    AssistantAnswerOut,
    AssistantQuestionsIn,
    AssistantResponseOut,
    CoverLetterOut,
    JobDetailOut,
    JobListOut,
    JobOut,
    MatchRunOut,
    RankedJobOut,
    ScanRunOut,
    ScanSourceResultOut,
    SearchRunOut,
    TailoredResumeOut,
    URLCheckResultOut,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Re-exported under the historical private names so every call site below
# (and the existing test suite, which patches/imports some of these)
# keeps working unchanged. The real implementations live in
# `job_agent.web.job_view` so `web/routers/companies.py` can share them
# instead of duplicating this serialization a second time.
_latest_match = job_view.latest_match
_application_for = job_view.application_for
_match_out = job_view.match_out
_job_out = job_view.job_out


def _source_name_map(session: Session) -> dict[int, str]:
    return {row.id: row.name for row in session.execute(select(JobSourceRow)).scalars()}


def _canonicalize_duplicates(
    jobs: list[JobRow], source_names: dict[int, str]
) -> list[tuple[JobRow, list[str], int]]:
    """Groups Job rows sharing a `job_fingerprint` (the same underlying
    posting seen on multiple sources — see `job_agent.jobs.fingerprint`'s
    module docstring for why the storage layer keeps every row rather
    than merging them) into ONE canonical representative per group, so
    the same job is never shown as several separate cards. The canonical
    row is whichever has the most recent `posted_at` (falling back to
    `discovered_at`) — the freshest signal about the SAME job, not a
    judgment about which source is "better". Returns
    (canonical_row, other_source_names, duplicate_count) triples."""
    groups: dict[str, list[JobRow]] = {}
    for job in jobs:
        groups.setdefault(job.job_fingerprint, []).append(job)

    out: list[tuple[JobRow, list[str], int]] = []
    for group in groups.values():
        canonical = max(group, key=lambda j: j.posted_at or j.discovered_at)
        others = [j for j in group if j.id != canonical.id]
        also_seen_on = sorted(
            {source_names.get(j.source_id, "?") for j in others if j.source_id is not None}
        )
        out.append((canonical, also_seen_on, len(group) - 1))
    return out


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
    include_inactive: bool = Query(
        default=False,
        description="Include CLOSED/EXPIRED postings — excluded by default (section 7: "
        "never keep recommending dead jobs).",
    ),
    sort: Literal["match", "newest", "salary", "company"] = Query(default="match"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    _, candidate_id = candidate
    jobs = list(session.execute(select(JobRow)).scalars())
    source_names = _source_name_map(session)

    items: list[JobOut] = []
    for job, also_seen_on, duplicate_count in _canonicalize_duplicates(jobs, source_names):
        match_row = _latest_match(session, job.id, candidate_id)
        application = _application_for(session, job.id, candidate_id)

        if not include_inactive and job.lifecycle_status != "ACTIVE":
            continue
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

        items.append(
            _job_out(
                job,
                match_row,
                application,
                source_name=source_names.get(job.source_id, None) if job.source_id else None,
                also_seen_on=also_seen_on,
                duplicate_count=duplicate_count,
            )
        )

    if sort == "match":
        items.sort(key=lambda j: j.match.overall_score if j.match else -1, reverse=True)
    elif sort == "newest":
        items.sort(key=lambda j: j.posted_at or j.discovered_at, reverse=True)
    elif sort == "salary":
        items.sort(key=lambda j: j.salary_max or j.salary_min or 0, reverse=True)
    elif sort == "company":
        items.sort(key=lambda j: j.company_name.lower())

    total = len(items)
    page = items[offset : offset + limit]
    return JobListOut(total=total, items=page)


def _search_run_out(run: SearchRunRow) -> SearchRunOut:
    return SearchRunOut(
        id=run.id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        sources=list(run.sources),
        queries=list(run.queries),
        jobs_found=run.jobs_found,
        duplicates_removed=run.duplicates_removed,
        expired_removed=run.expired_removed,
        qualified=run.qualified,
        errors=list(run.errors),
        status=run.status,
    )


@router.post("/search-run", response_model=SearchRunOut)
def run_search(session: SessionDep, candidate: CandidateDep, config: ConfigDep) -> SearchRunOut:
    """The full Phase 8 pipeline in one call: generate the candidate's
    search-query portfolio, scan every enabled source, sweep stale jobs
    to EXPIRED, match everything, and persist a `SearchRun` record —
    exactly what `job-agent jobs search-run` runs from the CLI."""
    profile, candidate_id = candidate
    llm = build_llm_provider(config)
    run = execute_search_run(session, config, profile, candidate_id, llm=llm)
    return _search_run_out(run)


# NOTE: every route below with a static path segment (search-runs, top10,
# apply-now) MUST be registered before `/{job_id}` — FastAPI matches
# routes in registration order, so a static path declared AFTER a `{job_
# id}` route would be swallowed by it (e.g. GET /jobs/top10 parsed as
# job_id="top10", a 422). This block stays above `/{job_id}` for exactly
# that reason; do not move it below without moving `/{job_id}` down too.
@router.get("/search-runs", response_model=list[SearchRunOut])
def list_search_runs(
    session: SessionDep, limit: int = Query(default=20, ge=1, le=100)
) -> list[SearchRunOut]:
    runs = session.execute(
        select(SearchRunRow).order_by(SearchRunRow.started_at.desc()).limit(limit)
    ).scalars()
    return [_search_run_out(r) for r in runs]


def _ranked_jobs(
    session: Session, config: AppConfig, candidate_id: int, *, limit: int | None
) -> list[RankedJobOut]:
    jobs = list(session.execute(select(JobRow)).scalars())
    pairs = [(job, _latest_match(session, job.id, candidate_id)) for job in jobs]
    preferences = compute_learned_preferences(
        job_view.matched_jobs_with_applications(session, candidate_id)
    )
    ranked = rank_jobs(
        pairs, config.automation.priority_weights, preferences=preferences, limit=limit
    )
    out = []
    for r in ranked:
        application = _application_for(session, r.job.id, candidate_id)
        out.append(
            RankedJobOut(
                job=_job_out(r.job, r.match, application),
                rank_score=r.rank_score,
                why=list(r.why),
                gaps=list(r.gaps),
                recommendation=r.recommendation,
            )
        )
    return out


@router.get("/top10", response_model=list[RankedJobOut])
def top_10(session: SessionDep, candidate: CandidateDep, config: ConfigDep) -> list[RankedJobOut]:
    """Section 9's "Today's Top 10" — ranked by candidate fit + freshness
    + career value + company fit + application viability, using
    `config/automation.yaml`'s `priority_weights`, never by match score
    alone. Never includes a CLOSED/EXPIRED posting."""
    _, candidate_id = candidate
    return _ranked_jobs(session, config, candidate_id, limit=10)


@router.get("/apply-now", response_model=list[RankedJobOut])
def apply_now_queue(
    session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> list[RankedJobOut]:
    """Section 10's APPLY NOW queue — the same ranking as Top 10, filtered
    to only the high-confidence APPLY decisions."""
    _, candidate_id = candidate
    ranked = _ranked_jobs(session, config, candidate_id, limit=None)
    return [r for r in ranked if r.job.match is not None and r.job.match.decision == "APPLY"]


def _job_detail_out(
    job: JobRow, match_row: JobMatchRow | None, application: ApplicationRow | None
) -> JobDetailOut:
    base = _job_out(job, match_row, application)
    return JobDetailOut(
        **base.model_dump(),
        description=job.description,
        requirements=job.requirements,
        preferred_qualifications=job.preferred_qualifications,
        visa_information=job.visa_information,
        company_url=job.company_url,
    )


@router.get("/compare", response_model=list[JobDetailOut])
def compare_jobs(
    session: SessionDep,
    candidate: CandidateDep,
    ids: str = Query(..., description="Comma-separated job ids, e.g. '12,45,78'."),
) -> list[JobDetailOut]:
    """Part 3.10's job comparison view: the same JobDetailOut every other
    view uses (match, data confidence, viability all included), just for
    several jobs at once so the frontend can lay them out side by side —
    never a second, separate comparison-specific computation."""
    try:
        job_ids = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="ids must be comma-separated integers."
        ) from exc
    if not (2 <= len(job_ids) <= 6):
        raise HTTPException(status_code=400, detail="Compare between 2 and 6 jobs at a time.")

    _, candidate_id = candidate
    results: list[JobDetailOut] = []
    for job_id in job_ids:
        job = session.get(JobRow, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
        match_row = _latest_match(session, job.id, candidate_id)
        application = _application_for(session, job.id, candidate_id)
        results.append(_job_detail_out(job, match_row, application))
    return results


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, session: SessionDep, candidate: CandidateDep) -> JobDetailOut:
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    _, candidate_id = candidate
    match_row = _latest_match(session, job.id, candidate_id)
    application = _application_for(session, job.id, candidate_id)
    return _job_detail_out(job, match_row, application)


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
    return _job_detail_out(job, match_row, application)


@router.post("/{job_id}/check-url", response_model=URLCheckResultOut)
def check_url(job_id: int, session: SessionDep) -> URLCheckResultOut:
    """The one live, on-demand part of application viability (Part 3.9's
    "URL works"): a single real outbound request against this job's
    application_url, triggered explicitly rather than on every page load
    (see `job_agent.jobs.url_check` for why). Never fabricates a result —
    a timeout or connection failure comes back UNKNOWN, not "broken"."""
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    if not job.application_url:
        raise HTTPException(status_code=400, detail="This job has no application URL to check.")
    result = check_application_url(job.application_url)
    return URLCheckResultOut(
        status=result.status, detail=result.detail, checked_at=result.checked_at
    )


@router.post("/{job_id}/tailor-resume", response_model=TailoredResumeOut)
def tailor_resume(
    job_id: int, session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> TailoredResumeOut:
    """Phase 9 section 11 — a job-specific resume tailoring: relevant
    skills/experience/projects reordered and selected from the candidate's
    OWN profile, plus ATS keywords the candidate already has. Uses the LLM
    only to refine the professional summary (when `ANTHROPIC_API_KEY` is
    configured); every other field is fully deterministic. Never invents
    experience, employers, skills, metrics, or education — see
    `job_agent.resume.tailor` for the fabrication guarantees."""
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    profile, _candidate_id = candidate
    llm = build_llm_provider(config)
    result = tailor_resume_for_job(
        profile,
        None,
        job_title=job.title,
        job_company=job.company_name,
        job_description=job.description,
        job_requirements=job.requirements,
        llm=llm,
    )
    return TailoredResumeOut(
        job_id=job_id,
        professional_summary=result.professional_summary,
        relevant_skills=list(result.relevant_skills),
        emphasized_experience=[e.model_dump(mode="json") for e in result.emphasized_experience],
        relevant_projects=[p.model_dump(mode="json") for p in result.relevant_projects],
        ats_keywords=list(result.ats_keywords),
        notes=list(result.notes),
        generated_by=result.generated_by,
    )


@router.post("/{job_id}/cover-letter", response_model=CoverLetterOut)
def cover_letter(
    job_id: int, session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> CoverLetterOut:
    """Phase 9 section 12 — a job-specific cover letter (never a generic
    template): references this job's own title/company and only the
    candidate's own overlapping skills/experience. Uses the LLM only when
    `ANTHROPIC_API_KEY` is configured; falls back to a deterministic
    letter otherwise. See `job_agent.applications.cover_letter` for the
    fabrication guarantees."""
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    profile, _candidate_id = candidate
    llm = build_llm_provider(config)
    result = generate_cover_letter(
        profile,
        job_title=job.title,
        job_company=job.company_name,
        job_description=job.description,
        llm=llm,
    )
    return CoverLetterOut(
        job_id=job_id,
        body=result.body,
        notes=list(result.notes),
        generated_by=result.generated_by,
    )


@router.post("/{job_id}/assistant", response_model=AssistantResponseOut)
def application_assistant(
    job_id: int,
    payload: AssistantQuestionsIn,
    session: SessionDep,
    candidate: CandidateDep,
    config: ConfigDep,
) -> AssistantResponseOut:
    """Phase 9 section 13 — ad-hoc answers to application questions the
    candidate types in, grounded entirely in their profile. Reuses the
    exact same `job_agent.applications.answer_engine.generate_answer`
    four-tier resolution (hard-block categories, trusted identity facts,
    answer bank, then a validated LLM draft) that `applications prepare`
    already uses for real ATS forms — never a second, separate answer
    pipeline."""
    job = session.get(JobRow, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id}.")
    profile, _candidate_id = candidate
    llm = build_llm_provider(config)
    resume_text = extract_resume_text(config.env.candidate_dir / "resume_master.docx")
    bank = load_answer_bank(config.env.candidate_dir / "answers")

    answers = []
    for text in payload.questions:
        question = ApplicationQuestion(text=text, category=classify_question(text))
        generated = generate_answer(question, profile, resume_text, bank, llm)
        answers.append(
            AssistantAnswerOut(
                question=generated.question,
                category=generated.category.value,
                answer=generated.answer,
                confidence=generated.confidence,
                source=generated.source,
                requires_human=generated.requires_human,
                validation_notes=list(generated.validation_notes),
            )
        )
    return AssistantResponseOut(job_id=job_id, answers=answers)


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

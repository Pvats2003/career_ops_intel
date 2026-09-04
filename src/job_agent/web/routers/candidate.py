"""Candidate profile + resume upload — reuses `job_agent.candidate.parser`
(structured extraction from `candidate/*.md`), `job_agent.resume.extractor`
(the authoritative resume text), and `job_agent.resume.service.
create_profile_version` (the SAME hallucination-guard validator the CLI's
`profile parse` command runs) without duplicating any of that logic here.

Uploading a resume never invents structure: it replaces
`candidate/resume_master.docx` on disk and re-runs the exact same
parse -> validate -> version pipeline the CLI already uses — the
candidate's own `candidate/*.md` files remain the source of truth for
what is asserted about them (section 3's "do NOT simply store the resume
as text" requirement), the uploaded file is only cross-checked against
that for consistency.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile
from sqlalchemy import select

from job_agent.applications.follow_up import compute_follow_up_recommendations
from job_agent.candidate.career_chat import answer_career_question
from job_agent.candidate.career_comparison import compare_career_paths
from job_agent.candidate.career_paths import discover_career_paths
from job_agent.candidate.career_profile import build_career_profile
from job_agent.candidate.explain import explain_ranking
from job_agent.candidate.learning import compute_learned_preferences, discover_insights
from job_agent.candidate.schema import CandidateProfile
from job_agent.candidate.skill_gap import discover_skill_gaps
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.llm.provider import build_llm_provider
from job_agent.matching.ranking import rank_jobs
from job_agent.resume.errors import ResumeExtractionError
from job_agent.resume.repository import list_versions
from job_agent.resume.service import create_profile_version
from job_agent.web import job_view
from job_agent.web.deps import CandidateDep, ConfigDep, SessionDep
from job_agent.web.schemas import (
    CandidateProfileOut,
    CareerChatIn,
    CareerChatOut,
    CareerPathComparisonRowOut,
    CareerPathOut,
    CareerProfileOut,
    CategoryInsightOut,
    InsightsOut,
    ResumeUploadResult,
    SkillGapEntryOut,
)

router = APIRouter(prefix="/api/candidate", tags=["candidate"])

_ALLOWED_RESUME_SUFFIXES = (".docx",)


def _years_experience(profile: CandidateProfile) -> float:
    """Rough, honest estimate from the parsed date ranges only — never a
    fabricated number. `end_date`/`start_date` are free-text (e.g.
    "2022-01", "Present") from the resume, so this only counts entries
    whose span it can actually parse; an unparsable entry is silently
    excluded rather than guessed at."""
    from datetime import UTC, datetime

    total_months = 0
    for entry in profile.experience:
        start = _parse_year_month(entry.start_date)
        end = (
            _parse_year_month(entry.end_date)
            if entry.end_date.strip().lower() not in ("present", "current", "")
            else (datetime.now(UTC).year, datetime.now(UTC).month)
        )
        if start is None or end is None:
            continue
        months = (end[0] - start[0]) * 12 + (end[1] - start[1])
        if months > 0:
            total_months += months
    return round(total_months / 12, 1)


def _parse_year_month(value: str) -> tuple[int, int] | None:
    value = value.strip()
    for fmt_len in (7, 4):
        candidate = value[:fmt_len]
        try:
            if len(candidate) == 7 and candidate[4] == "-":
                return int(candidate[:4]), int(candidate[5:7])
            if len(candidate) == 4 and candidate.isdigit():
                return int(candidate), 1
        except ValueError:
            continue
    return None


@router.get("/profile", response_model=CandidateProfileOut)
def get_profile(candidate: CandidateDep) -> CandidateProfileOut:
    profile, candidate_id = candidate
    return CandidateProfileOut(
        candidate_id=candidate_id,
        name=profile.identity_name.value,
        email=profile.contact_email.value,
        phone=profile.contact_phone.value,
        linkedin=profile.contact_linkedin.value,
        current_location=profile.identity_current_location.value,
        years_experience=_years_experience(profile),
        target_roles_primary=list(profile.target_roles.primary),
        target_roles_secondary=list(profile.target_roles.secondary),
        skills=[s.name for s in profile.skills],
        technical_skills=[s.name for s in profile.technical_skills],
        experience=[e.model_dump(mode="json") for e in profile.experience],
        education=[e.model_dump(mode="json") for e in profile.education],
        projects=[p.model_dump(mode="json") for p in profile.projects],
        achievements=[a.model_dump(mode="json") for a in profile.achievements],
        certifications=[c.model_dump(mode="json") for c in profile.certifications],
        source_files=list(profile.source_files),
        parsed_at=profile.parsed_at,
    )


@router.post("/resume", response_model=ResumeUploadResult)
async def upload_resume(
    file: UploadFile, session: SessionDep, config: ConfigDep
) -> ResumeUploadResult:
    if not file.filename or not file.filename.lower().endswith(_ALLOWED_RESUME_SUFFIXES):
        raise HTTPException(
            status_code=422,
            detail="Only a .docx resume is supported (job_agent.resume.extractor).",
        )
    body = await file.read()
    if not body:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    resume_path = config.env.candidate_dir / "resume_master.docx"
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    resume_path.write_bytes(body)

    from job_agent.candidate.parser import CandidateParseError, parse_candidate_profile
    from job_agent.db.repository import save_candidate_profile

    try:
        profile = parse_candidate_profile(config)
    except CandidateParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    candidate_id = save_candidate_profile(session, profile)
    session.commit()

    try:
        result = create_profile_version(session, config, profile, candidate_id)
        session.commit()
    except ResumeExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ResumeUploadResult(
        saved_path=str(resume_path),
        profile_version_id=result.version.id if result.version else None,
        validation_status=result.version.validation_status if result.version else "UNKNOWN",
        issues=[f"{issue.field}: {issue.detail}" for issue in result.issues],
    )


@router.get("/career-paths", response_model=list[CareerPathOut])
def get_career_paths(candidate: CandidateDep) -> list[CareerPathOut]:
    profile, _ = candidate
    results = discover_career_paths(profile)
    return [
        CareerPathOut(
            label=r.label,
            fit_score=r.fit_score,
            evidence=list(r.evidence),
            relevant_skills=list(r.relevant_skills),
            relevant_experience=list(r.relevant_experience),
            missing_skills=list(r.missing_skills),
            typical_titles=list(r.typical_titles),
            career_upside=r.career_upside,
            recommended_priority=r.recommended_priority,
        )
        for r in results
    ]


@router.get("/career-profile", response_model=CareerProfileOut)
def get_career_profile(candidate: CandidateDep) -> CareerProfileOut:
    """FINAL GOD MODE Part 2.4 — "what kind of career is this candidate
    building", derived entirely from `discover_career_paths` (never a
    second, separate judgment) plus the candidate's own stated location
    preferences. Recomputed fresh every call — no stored, staleness-prone
    snapshot."""
    profile, _ = candidate
    career_paths = discover_career_paths(profile)
    result = build_career_profile(profile, career_paths)
    return CareerProfileOut(
        primary_direction=result.primary_direction,
        strengths=list(result.strengths),
        growing_area=result.growing_area,
        skill_gaps=list(result.skill_gaps),
        best_locations=list(result.best_locations),
    )


@router.get("/career-paths/compare", response_model=list[CareerPathComparisonRowOut])
def get_career_path_comparison(
    session: SessionDep, candidate: CandidateDep
) -> list[CareerPathComparisonRowOut]:
    """FINAL GOD MODE Part 2.5 — career paths compared side by side on
    real signals only. `interview_rate` is `None` ("Insufficient data")
    below a minimum sample of real applications — see `job_agent.
    candidate.career_comparison` for every threshold used."""
    profile, candidate_id = candidate
    career_paths = discover_career_paths(profile)
    active_jobs = list(
        session.execute(select(JobRow).where(JobRow.lifecycle_status == "ACTIVE")).scalars()
    )
    applications = list(
        session.execute(
            select(ApplicationRow).where(ApplicationRow.candidate_id == candidate_id)
        ).scalars()
    )
    applications_with_jobs = []
    for application in applications:
        job = session.get(JobRow, application.job_id)
        if job is not None:
            applications_with_jobs.append((application, job))

    rows = compare_career_paths(career_paths, active_jobs, applications_with_jobs)
    return [
        CareerPathComparisonRowOut(
            label=r.label,
            current_fit=r.current_fit,
            job_volume=r.job_volume,
            career_upside=r.career_upside,
            skill_gap=r.skill_gap,
            interview_rate=r.interview_rate,
            interview_sample_size=r.interview_sample_size,
            overall=r.overall,
        )
        for r in rows
    ]


@router.get("/skill-gaps", response_model=list[SkillGapEntryOut])
def get_skill_gaps(session: SessionDep, candidate: CandidateDep) -> list[SkillGapEntryOut]:
    """FINAL GOD MODE Part 2.6 — the candidate's real, already-computed
    `JobMatch.missing_requirements` aggregated across their strongest
    matches. See `job_agent.candidate.skill_gap` for the exact, honest
    "opportunities unlocked" definition — never a guessed uplift number."""
    profile, candidate_id = candidate
    matched_job_ids = list(
        session.execute(
            select(JobMatchRow.job_id).where(JobMatchRow.candidate_id == candidate_id).distinct()
        ).scalars()
    )
    matches = [
        m
        for job_id in matched_job_ids
        if (m := job_view.latest_match(session, job_id, candidate_id)) is not None
    ]
    career_paths = discover_career_paths(profile)
    entries = discover_skill_gaps(matches, career_paths)
    return [
        SkillGapEntryOut(
            skill=e.skill,
            frequency_count=e.frequency_count,
            frequency_pct=e.frequency_pct,
            unlocks_count=e.unlocks_count,
            relevant_career_paths=list(e.relevant_career_paths),
        )
        for e in entries
    ]


@router.get("/insights", response_model=InsightsOut)
def get_insights(session: SessionDep, candidate: CandidateDep) -> InsightsOut:
    """Phase 12 section 21 — explainable behavioral patterns over jobs the
    candidate has actually been matched against: which ones they engaged
    with (saved/shortlisted/applied, tracked via `Application`) vs. left
    untouched, broken down by real job attributes. See `job_agent.
    candidate.learning` for how "notable" is decided — never a vague or
    overconfident claim from a handful of jobs."""
    _, candidate_id = candidate
    jobs_with_applications = job_view.matched_jobs_with_applications(session, candidate_id)
    categories, summary = discover_insights(jobs_with_applications)
    return InsightsOut(
        categories=[
            CategoryInsightOut(
                category=c.category,
                saved=c.saved,
                ignored=c.ignored,
                applied=c.applied,
                save_rate=c.save_rate,
                explanation=c.explanation,
            )
            for c in categories
        ],
        summary=summary,
    )


@router.get("/resume/versions")
def get_resume_versions(session: SessionDep, candidate: CandidateDep) -> list[dict]:
    _, candidate_id = candidate
    versions = list_versions(session, candidate_id)
    return [
        {
            "id": v.id,
            "validation_status": v.validation_status,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.post("/chat", response_model=CareerChatOut)
def career_chat(
    body: CareerChatIn, session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> CareerChatOut:
    """Part 7.20's Career Chat — every fact available to the answer comes
    from the same data Top 10/Career Profile/Follow-ups already compute,
    assembled fresh here (never re-derived differently or stored
    separately). With no LLM configured, the real data is returned
    directly rather than a fabricated "AI" answer."""
    profile, candidate_id = candidate
    grounded_in: list[str] = []

    jobs = list(session.execute(select(JobRow)).scalars())
    pairs = [(job, job_view.latest_match(session, job.id, candidate_id)) for job in jobs]
    preferences = compute_learned_preferences(
        job_view.matched_jobs_with_applications(session, candidate_id)
    )
    ranked = rank_jobs(pairs, config.automation.priority_weights, preferences=preferences, limit=10)
    top_jobs = [
        {
            "title": r.job.title,
            "company": r.job.company_name,
            "score": r.match.overall_score if r.match else None,
            "why": r.why[0] if r.why else r.recommendation,
        }
        for r in ranked
    ]
    if top_jobs:
        grounded_in.append(f"Top {len(top_jobs)} ranked jobs")

    career_paths = discover_career_paths(profile)
    career_profile_result = build_career_profile(profile, career_paths)
    career_profile_context = {
        "primary_direction": career_profile_result.primary_direction,
        "strengths": list(career_profile_result.strengths),
        "growing_area": career_profile_result.growing_area,
        "skill_gaps": list(career_profile_result.skill_gaps),
    }
    grounded_in.append("Career profile")

    applications = list(
        session.execute(
            select(ApplicationRow).where(ApplicationRow.candidate_id == candidate_id)
        ).scalars()
    )
    applications_with_jobs = []
    for app in applications:
        job = session.get(JobRow, app.job_id)
        if job is not None:
            applications_with_jobs.append((app, job))
    recommendations = compute_follow_up_recommendations(applications_with_jobs)
    follow_ups_context = [
        {
            "title": r.job.title,
            "company": r.job.company_name,
            "applied_days_ago": r.applied_days_ago,
            "suggested_action": r.suggested_action,
        }
        for r in recommendations
    ]
    if follow_ups_context:
        grounded_in.append("Pending follow-ups")

    context: dict = {
        "top_jobs": top_jobs,
        "career_profile": career_profile_context,
        "follow_ups": follow_ups_context,
    }

    if body.job_id is not None:
        job = session.get(JobRow, body.job_id)
        if job is not None:
            match_row = job_view.latest_match(session, job.id, candidate_id)
            job_ranked = rank_jobs(
                [(job, match_row)], config.automation.priority_weights, preferences=preferences
            )
            if job_ranked:
                breakdown = explain_ranking(job_ranked[0])
                context["specific_job"] = {
                    "title": job.title,
                    "company": job.company_name,
                    "rank_score": breakdown.rank_score,
                    "reasons": breakdown.reasons,
                    "main_weakness": breakdown.main_weakness,
                }
                grounded_in.append(f"Full detail for {job.title} at {job.company_name}")

    llm = build_llm_provider(config)
    response = answer_career_question(body.question, context, llm=llm)
    return CareerChatOut(
        answer=response.answer, generated_by=response.generated_by, grounded_in=grounded_in
    )

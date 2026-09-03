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

from job_agent.candidate.schema import CandidateProfile
from job_agent.resume.errors import ResumeExtractionError
from job_agent.resume.repository import list_versions
from job_agent.resume.service import create_profile_version
from job_agent.web.deps import CandidateDep, ConfigDep, SessionDep
from job_agent.web.schemas import CandidateProfileOut, ResumeUploadResult

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

"""Orchestrates one profile-versioning attempt: extract resume text,
validate the parsed profile against it, hash everything, and persist a new
version — or recognize nothing has changed and return the existing one.

`ResumeExtractionError` (resume file missing/corrupt) propagates — there is
nothing meaningful to persist if the authoritative source can't be read at
all, so this is a hard stop, not a recorded failure. A validation failure
(some fact couldn't be verified) is different: it IS recorded — as a
FAILED version, for the audit trail — and returned to the caller to act on,
rather than raised, matching how `job_agent.jobs.service`/`job_agent.
matching.service` report business-level outcomes as result objects and
reserve exceptions for "cannot proceed at all" conditions.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig
from job_agent.db.models import CandidateProfileVersion
from job_agent.resume.extractor import extract_resume_text
from job_agent.resume.repository import create_version, get_latest_version
from job_agent.resume.validator import ValidationIssue, validate_profile_against_resume
from job_agent.resume.versioning import compute_profile_hash, compute_source_hashes


@dataclass
class ProfileVersionResult:
    version: CandidateProfileVersion
    created: bool
    issues: list[ValidationIssue]

    @property
    def passed(self) -> bool:
        return self.version.validation_status == "PASSED"


def create_profile_version(
    session: Session,
    config: AppConfig,
    profile: CandidateProfile,
    candidate_id: int,
) -> ProfileVersionResult:
    resume_path = config.env.candidate_dir / "resume_master.docx"
    resume_text = extract_resume_text(resume_path)  # raises ResumeExtractionError, not caught here

    issues = validate_profile_against_resume(profile, resume_text)
    source_hashes = compute_source_hashes(config)
    profile_hash = compute_profile_hash(profile)
    resume_key = next(
        (k for k in source_hashes if k.endswith("resume_master.docx")), None
    )
    resume_file_hash = source_hashes[resume_key] if resume_key else ""

    existing = get_latest_version(session, candidate_id)
    if (
        existing is not None
        and existing.profile_hash == profile_hash
        and existing.resume_file_hash == resume_file_hash
        and existing.source_file_hashes == source_hashes
    ):
        # Identical to the last attempt (pass or fail) — nothing to record.
        return ProfileVersionResult(version=existing, created=False, issues=issues)

    validation_status = "PASSED" if not issues else "FAILED"
    row = create_version(
        session,
        candidate_id=candidate_id,
        profile_hash=profile_hash,
        resume_file_hash=resume_file_hash,
        source_file_hashes=source_hashes,
        snapshot=profile.model_dump(mode="json"),
        validation_status=validation_status,
        validation_issues=[{"field": i.field, "detail": i.detail} for i in issues],
    )
    session.commit()
    return ProfileVersionResult(version=row, created=True, issues=issues)

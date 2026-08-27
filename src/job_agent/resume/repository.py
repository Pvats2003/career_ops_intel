"""Insert-only persistence for candidate profile versions.

Never updates or deletes a row — see the `CandidateProfileVersion` model
docstring for why. `version_number` is assigned by this module (max + 1
per candidate), not by the caller, so it stays a reliable, gap-free
sequence regardless of how many times a version is attempted.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_agent.db.models import CandidateProfileVersion


def get_latest_version(session: Session, candidate_id: int) -> CandidateProfileVersion | None:
    """Most recent version by version_number, regardless of validation
    status — used to detect "nothing changed since last attempt"."""
    return session.execute(
        select(CandidateProfileVersion)
        .where(CandidateProfileVersion.candidate_id == candidate_id)
        .order_by(CandidateProfileVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_latest_verified_version(
    session: Session, candidate_id: int
) -> CandidateProfileVersion | None:
    """Most recent version that PASSED validation — this is what any
    Phase 5+ consumer (resume tailoring, applications) should read, never
    `get_latest_version`, so a failed re-parse never silently becomes the
    "current" profile something else relies on."""
    return session.execute(
        select(CandidateProfileVersion)
        .where(
            CandidateProfileVersion.candidate_id == candidate_id,
            CandidateProfileVersion.validation_status == "PASSED",
        )
        .order_by(CandidateProfileVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_versions(session: Session, candidate_id: int) -> list[CandidateProfileVersion]:
    return list(
        session.execute(
            select(CandidateProfileVersion)
            .where(CandidateProfileVersion.candidate_id == candidate_id)
            .order_by(CandidateProfileVersion.version_number.asc())
        ).scalars()
    )


def create_version(
    session: Session,
    *,
    candidate_id: int,
    profile_hash: str,
    resume_file_hash: str,
    source_file_hashes: dict[str, str],
    snapshot: dict,
    validation_status: str,
    validation_issues: list[dict],
) -> CandidateProfileVersion:
    next_number = (
        session.execute(
            select(func.max(CandidateProfileVersion.version_number)).where(
                CandidateProfileVersion.candidate_id == candidate_id
            )
        ).scalar_one()
        or 0
    ) + 1

    row = CandidateProfileVersion(
        candidate_id=candidate_id,
        version_number=next_number,
        profile_hash=profile_hash,
        resume_file_hash=resume_file_hash,
        source_file_hashes=source_file_hashes,
        snapshot=snapshot,
        validation_status=validation_status,
        validation_issues=validation_issues,
    )
    session.add(row)
    session.flush()
    return row

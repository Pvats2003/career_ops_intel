from __future__ import annotations

import shutil
from datetime import UTC, datetime

import pytest

from job_agent.candidate.schema import EvidenceLevel, ExperienceEntry, SkillFact
from job_agent.config.loader import load_config
from job_agent.db.models import Candidate, CandidateProfileVersion
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.resume.errors import ResumeExtractionError
from job_agent.resume.repository import get_latest_verified_version, list_versions
from job_agent.resume.service import create_profile_version


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture()
def candidate_row(db_session):
    row = Candidate(
        name="Test", email="t@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_first_call_creates_passed_version(db_session, candidate_row, real_config, real_profile):
    result = create_profile_version(db_session, real_config, real_profile, candidate_row.id)
    assert result.created is True
    assert result.passed is True
    assert result.version.version_number == 1
    assert result.issues == []


def test_rerun_with_identical_profile_is_noop(db_session, candidate_row, real_config, real_profile):
    first = create_profile_version(db_session, real_config, real_profile, candidate_row.id)
    second = create_profile_version(db_session, real_config, real_profile, candidate_row.id)
    assert second.created is False
    assert second.version.id == first.version.id
    assert db_session.query(CandidateProfileVersion).count() == 1


def test_changed_profile_content_creates_new_version(
    db_session, candidate_row, real_config, real_profile
):
    create_profile_version(db_session, real_config, real_profile, candidate_row.id)

    changed_profile = real_profile.model_copy(
        update={
            "identity_current_location": real_profile.identity_current_location.model_copy(
                update={"value": "Bengaluru, Karnataka, India"}
            )
        }
    )
    result = create_profile_version(db_session, real_config, changed_profile, candidate_row.id)
    assert result.created is True
    assert result.version.version_number == 2
    assert db_session.query(CandidateProfileVersion).count() == 2


def test_validation_failure_creates_failed_version_not_silently(
    db_session, candidate_row, real_config, real_profile
):
    fabricated = real_profile.model_copy(
        update={
            "experience": (
                *real_profile.experience,
                ExperienceEntry(
                    title="Chief Fabrication Officer",
                    company="Nonexistent Industries",
                    start_date="2020-01",
                    end_date="2021-01",
                    source="fabricated",
                ),
            )
        }
    )
    result = create_profile_version(db_session, real_config, fabricated, candidate_row.id)

    assert result.created is True  # the FAILED attempt is still recorded, not dropped
    assert result.passed is False
    assert len(result.issues) >= 2  # fake title + fake company
    assert result.version.validation_status == "FAILED"

    # A failed version must never be returned as the "current, trustworthy" one.
    assert get_latest_verified_version(db_session, candidate_row.id) is None
    # But it IS visible in the full history — never silently dropped.
    assert len(list_versions(db_session, candidate_row.id)) == 1


def test_passed_version_survives_a_later_failed_attempt(
    db_session, candidate_row, real_config, real_profile
):
    good = create_profile_version(db_session, real_config, real_profile, candidate_row.id)
    assert good.passed is True

    fabricated = real_profile.model_copy(
        update={
            "skills": (
                *real_profile.skills,
                SkillFact(
                    name="Completely Invented Skill",
                    category="technical",
                    evidence_level=EvidenceLevel.HAS,
                    source="fabricated",
                    confidence=1.0,
                    verified=True,
                ),
            )
        }
    )
    bad = create_profile_version(db_session, real_config, fabricated, candidate_row.id)
    assert bad.passed is False

    # get_latest_verified_version must still return the earlier PASSED one,
    # never the newer FAILED one — this is the entire point of separating
    # "latest" from "latest verified".
    still_current = get_latest_verified_version(db_session, candidate_row.id)
    assert still_current.id == good.version.id
    assert len(list_versions(db_session, candidate_row.id)) == 2


def test_missing_resume_file_raises_and_persists_nothing(
    db_session, candidate_row, real_config, real_profile, tmp_path
):
    candidate_dir = tmp_path / "candidate"
    shutil.copytree(real_config.env.candidate_dir, candidate_dir)
    (candidate_dir / "resume_master.docx").unlink()

    broken_config = load_config(config_dir=real_config.env.config_dir)
    broken_config.env.candidate_dir = candidate_dir  # type: ignore[misc]

    with pytest.raises(ResumeExtractionError):
        create_profile_version(db_session, broken_config, real_profile, candidate_row.id)

    assert db_session.query(CandidateProfileVersion).count() == 0

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.db.models import Candidate, CandidateProfileVersion
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.resume.repository import (
    create_version,
    get_latest_verified_version,
    get_latest_version,
    list_versions,
)


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


def _create(session, candidate_id, *, status="PASSED", profile_hash="ph1"):
    return create_version(
        session,
        candidate_id=candidate_id,
        profile_hash=profile_hash,
        resume_file_hash="rh1",
        source_file_hashes={"candidate/resume_master.docx": "rh1"},
        snapshot={"name": "test"},
        validation_status=status,
        validation_issues=[],
    )


def test_create_version_assigns_sequential_numbers(db_session, candidate_row):
    v1 = _create(db_session, candidate_row.id)
    v2 = _create(db_session, candidate_row.id, profile_hash="ph2")
    db_session.commit()
    assert v1.version_number == 1
    assert v2.version_number == 2


def test_version_numbers_are_independent_per_candidate(db_session):
    c1 = Candidate(
        name="A", email="a@x.com", phone="1", linkedin="a",
        current_location="x", parsed_at=datetime.now(UTC),
    )
    c2 = Candidate(
        name="B", email="b@x.com", phone="2", linkedin="b",
        current_location="x", parsed_at=datetime.now(UTC),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    v1 = _create(db_session, c1.id)
    v2 = _create(db_session, c2.id)
    db_session.commit()
    assert v1.version_number == 1
    assert v2.version_number == 1  # independent sequence per candidate


def test_create_version_is_insert_only(db_session, candidate_row):
    _create(db_session, candidate_row.id, profile_hash="ph1")
    _create(db_session, candidate_row.id, profile_hash="ph2")
    db_session.commit()
    assert db_session.query(CandidateProfileVersion).count() == 2


def test_get_latest_version_returns_most_recent_regardless_of_status(db_session, candidate_row):
    _create(db_session, candidate_row.id, status="PASSED", profile_hash="ph1")
    failed = _create(db_session, candidate_row.id, status="FAILED", profile_hash="ph2")
    db_session.commit()

    latest = get_latest_version(db_session, candidate_row.id)
    assert latest.id == failed.id


def test_get_latest_verified_version_skips_failed(db_session, candidate_row):
    passed = _create(db_session, candidate_row.id, status="PASSED", profile_hash="ph1")
    _create(db_session, candidate_row.id, status="FAILED", profile_hash="ph2")
    db_session.commit()

    verified = get_latest_verified_version(db_session, candidate_row.id)
    assert verified.id == passed.id


def test_get_latest_verified_version_none_when_all_failed(db_session, candidate_row):
    _create(db_session, candidate_row.id, status="FAILED", profile_hash="ph1")
    db_session.commit()
    assert get_latest_verified_version(db_session, candidate_row.id) is None


def test_list_versions_ordered_oldest_first(db_session, candidate_row):
    _create(db_session, candidate_row.id, profile_hash="ph1")
    _create(db_session, candidate_row.id, profile_hash="ph2")
    _create(db_session, candidate_row.id, profile_hash="ph3")
    db_session.commit()

    versions = list_versions(db_session, candidate_row.id)
    assert [v.version_number for v in versions] == [1, 2, 3]


def test_versions_are_never_deleted_or_mutated(db_session, candidate_row):
    v1 = _create(db_session, candidate_row.id, profile_hash="ph1")
    db_session.commit()
    original_hash = v1.profile_hash

    _create(db_session, candidate_row.id, profile_hash="ph2")
    db_session.commit()

    reloaded = db_session.get(CandidateProfileVersion, v1.id)
    assert reloaded is not None
    assert reloaded.profile_hash == original_hash

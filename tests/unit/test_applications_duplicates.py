from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.applications.duplicates import find_cross_source_duplicate_application
from job_agent.applications.repository import get_or_create_application
from job_agent.db.models import Candidate, Company, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture()
def candidate(db_session):
    candidate = Candidate(
        name="Test Candidate", email="test@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(candidate)
    db_session.flush()
    return candidate


def _job(db_session, *, source_name: str, fingerprint: str) -> JobRow:
    company = Company(name="Acme")
    db_session.add(company)
    db_session.flush()
    source = JobSource(name=source_name, kind="ats_api", enabled=True)
    db_session.add(source)
    db_session.flush()
    job = JobRow(
        source_id=source.id, source_job_id="1", company_id=company.id, company_name="Acme",
        title="Associate Product Manager", application_url=f"https://{source_name}.test/1",
        job_fingerprint=fingerprint,
    )
    db_session.add(job)
    db_session.flush()
    return job


def test_finds_existing_application_for_same_fingerprint_different_job(db_session, candidate):
    greenhouse_job = _job(db_session, source_name="greenhouse", fingerprint="shared-fp")
    lever_job = _job(db_session, source_name="lever", fingerprint="shared-fp")

    existing_application, _ = get_or_create_application(
        db_session, greenhouse_job.id, candidate.id, dry_run=True
    )
    db_session.commit()

    duplicate = find_cross_source_duplicate_application(db_session, lever_job, candidate.id)
    assert duplicate is not None
    assert duplicate.id == existing_application.id


def test_no_duplicate_when_fingerprint_unique(db_session, candidate):
    job = _job(db_session, source_name="greenhouse", fingerprint="unique-fp")
    assert find_cross_source_duplicate_application(db_session, job, candidate.id) is None


def test_does_not_flag_the_jobs_own_application_as_a_duplicate_of_itself(db_session, candidate):
    job = _job(db_session, source_name="greenhouse", fingerprint="shared-fp")
    get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    assert find_cross_source_duplicate_application(db_session, job, candidate.id) is None


def test_no_duplicate_when_other_job_shares_fingerprint_but_has_no_application(
    db_session, candidate
):
    greenhouse_job = _job(db_session, source_name="greenhouse", fingerprint="shared-fp")
    _job(db_session, source_name="lever", fingerprint="shared-fp")
    db_session.commit()

    assert (
        find_cross_source_duplicate_application(db_session, greenhouse_job, candidate.id) is None
    )

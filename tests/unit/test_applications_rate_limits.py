from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from job_agent.applications.rate_limits import check_rate_limits
from job_agent.config.models import ApplicationLimits
from job_agent.db.models import Application, Candidate, Company, JobSource
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
def job_and_candidate(db_session):
    company = Company(name="Acme")
    db_session.add(company)
    db_session.flush()
    source = JobSource(name="greenhouse", kind="ats_api", enabled=True)
    db_session.add(source)
    db_session.flush()
    job = JobRow(
        source_id=source.id, source_job_id="1", company_id=company.id, company_name="Acme",
        title="Associate Product Manager", application_url="https://x.test/1",
        job_fingerprint="fp1",
    )
    db_session.add(job)
    candidate = Candidate(
        name="Test Candidate", email="test@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(candidate)
    db_session.flush()
    return job, candidate


def _limits(**overrides) -> ApplicationLimits:
    return ApplicationLimits(**overrides)


def _submit(db_session, job, candidate, when):
    db_session.add(
        Application(job_id=job.id, candidate_id=candidate.id, status="SUBMITTED", submitted_at=when)
    )
    db_session.commit()


def test_allows_when_under_all_limits(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    result = check_rate_limits(db_session, candidate.id, job, _limits())
    assert result.allowed is True
    assert result.reason is None


def test_blocks_when_daily_limit_reached(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    now = datetime.now(UTC)
    _submit(db_session, job, candidate, now)
    result = check_rate_limits(db_session, candidate.id, job, _limits(max_per_day=1), now=now)
    assert result.allowed is False
    assert "daily" in result.reason


def test_blocks_when_hourly_limit_reached(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    now = datetime.now(UTC)
    _submit(db_session, job, candidate, now)
    result = check_rate_limits(
        db_session, candidate.id, job, _limits(max_per_day=100, max_per_hour=1), now=now
    )
    assert result.allowed is False
    assert "hourly" in result.reason


def test_blocks_when_per_company_lifetime_limit_reached(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    old = datetime.now(UTC) - timedelta(days=100)
    _submit(db_session, job, candidate, old)
    result = check_rate_limits(
        db_session, candidate.id, job,
        _limits(max_per_day=100, max_per_hour=100, max_per_company=1),
    )
    assert result.allowed is False
    assert "company" in result.reason


def test_blocks_when_per_source_daily_limit_reached(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    now = datetime.now(UTC)
    _submit(db_session, job, candidate, now)
    result = check_rate_limits(
        db_session, candidate.id, job,
        _limits(max_per_day=100, max_per_hour=100, max_per_company=100, max_per_source_per_day=1),
        now=now,
    )
    assert result.allowed is False
    assert "source" in result.reason


def test_old_submissions_outside_rolling_window_do_not_count(db_session, job_and_candidate):
    """max_per_company is a lifetime cap (see rate_limits.py), so it must be
    raised too — this test isolates the *rolling* day/hour windows only."""
    job, candidate = job_and_candidate
    now = datetime.now(UTC)
    _submit(db_session, job, candidate, now - timedelta(days=2))
    result = check_rate_limits(
        db_session, candidate.id, job, _limits(max_per_day=1, max_per_company=100), now=now
    )
    assert result.allowed is True

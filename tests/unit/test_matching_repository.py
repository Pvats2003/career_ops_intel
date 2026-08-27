from __future__ import annotations

import pytest

from job_agent.db.models import Candidate, Company, JobMatch, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.matching.repository import save_job_match
from job_agent.matching.schema import Decision, JobMatchResult


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
        current_location="Remote", parsed_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    db_session.add(candidate)
    db_session.flush()
    return job, candidate


def _result(**overrides) -> JobMatchResult:
    defaults = dict(
        overall_score=80, decision=Decision.REVIEW,
        skills_match=80, experience_match=80, role_match=80, project_match=80,
        education_match=80, location_match=80, seniority_match=80, eligibility_match=80,
        reasoning="ok", semantic_available=False,
    )
    defaults.update(overrides)
    return JobMatchResult(**defaults)


def test_save_job_match_persists_all_fields(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    result = _result(
        missing_requirements=("SQL",), concerns=("note",),
        hard_stop_reasons=("seniority_mismatch",), excluded_reasons=(),
    )
    row = save_job_match(db_session, job_id=job.id, candidate_id=candidate.id, result=result)
    db_session.commit()

    fetched = db_session.get(JobMatch, row.id)
    assert fetched.overall_score == 80
    assert fetched.decision == "REVIEW"
    assert fetched.missing_requirements == ["SQL"]
    assert fetched.hard_stop_reasons == ["seniority_mismatch"]
    assert fetched.semantic_available is False


def test_save_job_match_is_insert_only(db_session, job_and_candidate):
    """Re-matching the same job must create a NEW row, not overwrite the
    previous one — job_matches is an audit trail, not current-state cache."""
    job, candidate = job_and_candidate
    save_job_match(db_session, job_id=job.id, candidate_id=candidate.id, result=_result())
    save_job_match(
        db_session, job_id=job.id, candidate_id=candidate.id,
        result=_result(overall_score=95, decision=Decision.APPLY),
    )
    db_session.commit()
    rows = db_session.query(JobMatch).filter_by(job_id=job.id).all()
    assert len(rows) == 2
    scores = sorted(r.overall_score for r in rows)
    assert scores == [80, 95]

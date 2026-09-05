"""job_agent.web.job_view — batched match/application lookup helpers.

Dashboard-loading forensic audit: `matched_jobs_with_applications()` used
to call `session.get(JobRow, job_id)` AND `application_for()` once per
distinct matched job id — an unbounded N+1 on each. These tests prove the
batched replacement (`applications_by_job()` + one batched Job query)
preserves the exact same pairing/semantics while eliminating the O(N)
round-trips.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import event

from job_agent.applications.repository import get_or_create_application
from job_agent.db.models import Candidate, JobMatch, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.web.job_view import applications_by_job, matched_jobs_with_applications


@contextmanager
def _counting_queries_touching(engine, *table_names: str):
    counts = {"n": 0}

    def _listener(conn, cursor, statement, *args):
        if any(name in statement for name in table_names):
            counts["n"] += 1

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


@pytest.fixture()
def engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture()
def session(engine):
    factory = get_session_factory(engine)
    with factory() as s:
        yield s


def _candidate(session, *, email="test@example.com") -> Candidate:
    candidate = Candidate(
        name="Test Candidate", email=email, phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    session.add(candidate)
    session.flush()
    return candidate


def _source(session) -> JobSource:
    source = JobSource(name="greenhouse", kind="ats_api", enabled=True)
    session.add(source)
    session.flush()
    return source


def _job(session, source, *, fingerprint: str) -> JobRow:
    job = JobRow(
        source_id=source.id, company_name="Acme", title="Business Analyst",
        application_url="https://x.test/1", job_fingerprint=fingerprint,
    )
    session.add(job)
    session.flush()
    return job


def _match(session, job_id: int, candidate_id: int) -> None:
    session.add(
        JobMatch(
            job_id=job_id, candidate_id=candidate_id, overall_score=80, decision="REVIEW",
            reasoning="ok", semantic_available=False,
        )
    )
    session.commit()


def test_applications_by_job_batches_into_one_query(session, engine):
    source = _source(session)
    candidate = _candidate(session)
    job_ids = [_job(session, source, fingerprint=f"fp{i}").id for i in range(5)]
    for job_id in job_ids:
        get_or_create_application(session, job_id, candidate.id, dry_run=True)[0]

    with _counting_queries_touching(engine, "applications") as counts:
        result = applications_by_job(session, job_ids, candidate.id)

    assert len(result) == 5
    assert counts["n"] == 1, f"expected exactly 1 batched query, got {counts['n']}"


def test_applications_by_job_jobs_without_applications_are_absent(session):
    source = _source(session)
    candidate = _candidate(session)
    with_app = _job(session, source, fingerprint="with-app")
    without_app = _job(session, source, fingerprint="without-app")
    get_or_create_application(session, with_app.id, candidate.id, dry_run=True)

    result = applications_by_job(session, [with_app.id, without_app.id], candidate.id)

    assert with_app.id in result
    assert without_app.id not in result


def test_applications_by_job_candidate_isolation(session):
    source = _source(session)
    candidate_a = _candidate(session, email="a@example.com")
    candidate_b = _candidate(session, email="b@example.com")
    job = _job(session, source, fingerprint="shared-job")
    get_or_create_application(session, job.id, candidate_a.id, dry_run=True)

    result_for_b = applications_by_job(session, [job.id], candidate_b.id)
    result_for_a = applications_by_job(session, [job.id], candidate_a.id)

    assert job.id not in result_for_b
    assert job.id in result_for_a


def test_matched_jobs_with_applications_batches_regardless_of_job_count(session, engine):
    """Fails against the pre-fix per-job-id loop (5 jobs -> 5 SELECTs
    against applications, plus 5 more against jobs) and passes against
    the batched queries (1 each)."""
    source = _source(session)
    candidate = _candidate(session)
    job_ids = [_job(session, source, fingerprint=f"mja-{i}").id for i in range(5)]
    for job_id in job_ids:
        _match(session, job_id, candidate.id)
        get_or_create_application(session, job_id, candidate.id, dry_run=True)[0]

    with _counting_queries_touching(engine, "applications", "jobs") as counts:
        pairs = matched_jobs_with_applications(session, candidate.id)

    assert len(pairs) == 5
    assert counts["n"] < 5, (
        f"expected a bounded number of jobs/applications queries regardless "
        f"of job count (5), got {counts['n']} — looks like a reintroduced N+1 query"
    )


def test_matched_jobs_with_applications_preserves_pairing_semantics(session):
    """Jobs with a real application pair with it; jobs matched but never
    engaged with pair with None — never fabricated, never dropped."""
    source = _source(session)
    candidate = _candidate(session)
    applied_job = _job(session, source, fingerprint="applied")
    untouched_job = _job(session, source, fingerprint="untouched")
    _match(session, applied_job.id, candidate.id)
    _match(session, untouched_job.id, candidate.id)
    application, _ = get_or_create_application(session, applied_job.id, candidate.id, dry_run=True)

    pairs = dict(matched_jobs_with_applications(session, candidate.id))

    assert pairs[applied_job].id == application.id
    assert pairs[untouched_job] is None


def test_matched_jobs_with_applications_candidate_isolation(session):
    source = _source(session)
    candidate_a = _candidate(session, email="a2@example.com")
    candidate_b = _candidate(session, email="b2@example.com")
    job = _job(session, source, fingerprint="isolation-job")
    _match(session, job.id, candidate_a.id)
    # Candidate B was never matched against this job at all.

    pairs_a = matched_jobs_with_applications(session, candidate_a.id)
    pairs_b = matched_jobs_with_applications(session, candidate_b.id)

    assert [j.id for j, _ in pairs_a] == [job.id]
    assert pairs_b == []


def test_matched_jobs_with_applications_never_duplicates_a_job(session):
    """A job matched multiple times (re-matched on a later search run)
    must appear exactly once, not once per JobMatch row."""
    source = _source(session)
    candidate = _candidate(session)
    job = _job(session, source, fingerprint="rematched")
    _match(session, job.id, candidate.id)
    _match(session, job.id, candidate.id)  # a second match run against the same job

    pairs = matched_jobs_with_applications(session, candidate.id)

    assert len(pairs) == 1
    assert pairs[0][0].id == job.id

"""Notification generation (job_agent.jobs.notifications) — Career OS
Phase 11 section 20."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

from job_agent.db.models import Candidate as CandidateRow
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.db.models import Notification as NotificationRow
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.notifications import (
    DREAM_COMPANY,
    FRESH_JOB,
    HIGH_MATCH,
    generate_notifications,
)

_fingerprint_counter = itertools.count()


def _session(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session = get_session_factory(engine)()
    session.add(
        CandidateRow(
            id=1, name="Test Candidate", email="test@example.invalid", phone="+1-555-0100",
            linkedin="https://linkedin.com/in/test", current_location="Remote",
            parsed_at=datetime.now(UTC),
        )
    )
    session.flush()
    return session


def _job(session, **overrides) -> JobRow:
    base = dict(
        company_name="Acme Corp", title="Business Analyst", location="Remote",
        remote_type="remote", job_fingerprint=f"fp-{next(_fingerprint_counter)}",
        lifecycle_status="ACTIVE", freshness_status="NEW",
    )
    base.update(overrides)
    job = JobRow(**base)
    session.add(job)
    session.flush()
    return job


def _match(session, job_id, candidate_id=1, **overrides) -> JobMatchRow:
    base = dict(
        job_id=job_id, candidate_id=candidate_id, overall_score=80, decision="APPLY",
        reasoning="Strong overlap.", missing_requirements=[], concerns=[],
        semantic_available=False,
    )
    base.update(overrides)
    match = JobMatchRow(**base)
    session.add(match)
    session.flush()
    return match


def test_high_match_notification_created_above_threshold(tmp_path):
    session = _session(tmp_path)
    job = _job(session)
    match = _match(session, job.id, overall_score=95)
    created = generate_notifications(session, 1, [(job, match)], min_score=90)
    assert len(created) == 1
    assert created[0].event_type == HIGH_MATCH


def test_no_notification_below_threshold(tmp_path):
    session = _session(tmp_path)
    job = _job(session)
    match = _match(session, job.id, overall_score=70)
    created = generate_notifications(session, 1, [(job, match)], min_score=90)
    assert created == []


def test_never_notifies_twice_for_same_job_and_event(tmp_path):
    session = _session(tmp_path)
    job = _job(session)
    match = _match(session, job.id, overall_score=95)
    first = generate_notifications(session, 1, [(job, match)], min_score=90)
    second = generate_notifications(session, 1, [(job, match)], min_score=90)
    assert len(first) == 1
    assert second == []
    total = session.query(NotificationRow).count()
    assert total == 1


def test_dream_company_notification_from_watchlist(tmp_path):
    session = _session(tmp_path)
    session.add(WatchlistEntryRow(candidate_id=1, kind="COMPANY", value="Acme Corp"))
    session.flush()
    job = _job(session)
    created = generate_notifications(session, 1, [(job, None)], min_score=90)
    assert any(n.event_type == DREAM_COMPANY for n in created)


def test_fresh_job_notification_only_for_fresh_postings(tmp_path):
    session = _session(tmp_path)
    session.add(WatchlistEntryRow(candidate_id=1, kind="ROLE", value="Business Analyst"))
    session.flush()
    fresh_job = _job(session, freshness_status="JUST_POSTED")
    stale_job = _job(session, freshness_status="OLD")
    pairs = [(fresh_job, None), (stale_job, None)]
    created = generate_notifications(session, 1, pairs, min_score=90)
    fresh_job_ids = {n.related_job_id for n in created if n.event_type == FRESH_JOB}
    assert fresh_job.id in fresh_job_ids
    assert stale_job.id not in fresh_job_ids


def test_inactive_jobs_never_generate_notifications(tmp_path):
    session = _session(tmp_path)
    job = _job(session, lifecycle_status="CLOSED")
    match = _match(session, job.id, overall_score=99)
    created = generate_notifications(session, 1, [(job, match)], min_score=90)
    assert created == []


def test_empty_batch_never_crashes(tmp_path):
    session = _session(tmp_path)
    assert generate_notifications(session, 1, [], min_score=90) == []

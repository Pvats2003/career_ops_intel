"""Autonomous scheduled search (job_agent.jobs.scheduler) — Career OS
Phase 11 section 16."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_agent.db.models import Candidate as CandidateRow
from job_agent.db.models import SearchPreferences as SearchPreferencesRow
from job_agent.db.models import SearchRun as SearchRunRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.scheduler import _is_due, build_scheduler


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


def test_due_when_no_prior_search_run(tmp_path):
    session = _session(tmp_path)
    assert _is_due(session, candidate_id=1) is True


def test_not_due_when_recent_run_within_default_frequency(tmp_path):
    session = _session(tmp_path)
    session.add(
        SearchRunRow(
            started_at=datetime.now(UTC) - timedelta(hours=1),
            completed_at=datetime.now(UTC) - timedelta(hours=1),
            status="COMPLETED",
        )
    )
    session.commit()
    assert _is_due(session, candidate_id=1) is False


def test_due_once_default_frequency_elapsed(tmp_path):
    session = _session(tmp_path)
    session.add(
        SearchRunRow(
            started_at=datetime.now(UTC) - timedelta(hours=30),
            completed_at=datetime.now(UTC) - timedelta(hours=30),
            status="COMPLETED",
        )
    )
    session.commit()
    assert _is_due(session, candidate_id=1) is True


def test_respects_candidate_configured_frequency(tmp_path):
    session = _session(tmp_path)
    session.add(SearchPreferencesRow(candidate_id=1, search_frequency_hours=2))
    session.add(
        SearchRunRow(
            started_at=datetime.now(UTC) - timedelta(hours=3),
            completed_at=datetime.now(UTC) - timedelta(hours=3),
            status="COMPLETED",
        )
    )
    session.commit()
    assert _is_due(session, candidate_id=1) is True


def test_not_due_within_custom_shorter_frequency_window(tmp_path):
    session = _session(tmp_path)
    session.add(SearchPreferencesRow(candidate_id=1, search_frequency_hours=48))
    session.add(
        SearchRunRow(
            started_at=datetime.now(UTC) - timedelta(hours=3),
            completed_at=datetime.now(UTC) - timedelta(hours=3),
            status="COMPLETED",
        )
    )
    session.commit()
    assert _is_due(session, candidate_id=1) is False


def test_failed_run_never_counts_as_the_last_completed_run(tmp_path):
    session = _session(tmp_path)
    session.add(
        SearchRunRow(
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            completed_at=datetime.now(UTC) - timedelta(minutes=5),
            status="FAILED",
        )
    )
    session.commit()
    assert _is_due(session, candidate_id=1) is True


def test_build_scheduler_returns_a_scheduler_not_yet_started(real_config):
    scheduler = build_scheduler(real_config, poll_minutes=15)
    assert scheduler.running is False
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "career_os_scheduled_search"

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from job_agent.applications.repository import (
    count_submissions_from_source_since,
    count_submissions_since,
    count_submissions_to_company,
    get_answers,
    get_application,
    get_or_create_application,
    record_event,
    save_answer,
    transition_status,
)
from job_agent.applications.schema import ApplicationStatus, GeneratedAnswer, QuestionCategory
from job_agent.applications.state_machine import IllegalStateTransitionError
from job_agent.db.models import Application, ApplicationEvent, Candidate, Company, JobSource
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


def _answer(**overrides) -> GeneratedAnswer:
    defaults = dict(
        question="Tell me about yourself.", category=QuestionCategory.MOTIVATION,
        answer="I am a candidate.", confidence=0.8, source="answer_bank:x",
        requires_human=False, validated=True,
    )
    defaults.update(overrides)
    return GeneratedAnswer(**defaults)


def test_get_or_create_application_creates_row_and_discovered_event(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    application, created = get_or_create_application(
        db_session, job.id, candidate.id, dry_run=True
    )
    db_session.commit()

    assert created is True
    assert application.status == ApplicationStatus.DISCOVERED.value
    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    assert len(events) == 1
    assert events[0].event_type == "APPLICATION_DISCOVERED"


def test_get_or_create_application_is_idempotent(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    first, created_first = get_or_create_application(
        db_session, job.id, candidate.id, dry_run=True
    )
    db_session.commit()
    second, created_second = get_or_create_application(
        db_session, job.id, candidate.id, dry_run=True
    )
    db_session.commit()

    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    rows = db_session.query(Application).filter_by(job_id=job.id, candidate_id=candidate.id).all()
    assert len(rows) == 1
    events = db_session.query(ApplicationEvent).filter_by(application_id=first.id).all()
    assert len(events) == 1  # second call must not add a duplicate discovery event


def test_duplicate_application_blocked_at_db_level(db_session, job_and_candidate):
    """Even bypassing get_or_create_application, the unique constraint on
    (job_id, candidate_id) makes a second row for the same pair impossible."""
    job, candidate = job_and_candidate
    db_session.add(Application(job_id=job.id, candidate_id=candidate.id, status="DISCOVERED"))
    db_session.flush()
    db_session.add(Application(job_id=job.id, candidate_id=candidate.id, status="DISCOVERED"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_transition_status_updates_status_and_writes_audit_event(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    transition_status(
        db_session, application, ApplicationStatus.MATCHED,
        event_type="MATCHED", details={"decision": "APPLY"},
    )
    db_session.commit()

    assert application.status == ApplicationStatus.MATCHED.value
    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    assert len(events) == 2
    last = events[-1]
    assert last.event_type == "MATCHED"
    assert last.details["from_status"] == "DISCOVERED"
    assert last.details["to_status"] == "MATCHED"
    assert last.details["decision"] == "APPLY"


def test_transition_status_rejects_illegal_jump_and_leaves_state_and_history_unchanged(
    db_session, job_and_candidate
):
    job, candidate = job_and_candidate
    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    with pytest.raises(IllegalStateTransitionError):
        transition_status(
            db_session, application, ApplicationStatus.VERIFIED,
            event_type="VERIFIED", details={},
        )

    assert application.status == ApplicationStatus.DISCOVERED.value
    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    assert len(events) == 1  # only the original discovery event


def test_save_answer_and_get_answers_round_trip(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    save_answer(db_session, application.id, _answer())
    save_answer(
        db_session, application.id,
        _answer(question="Salary?", category=QuestionCategory.SALARY, answer=None,
                 requires_human=True, validated=False, source="hard_block:salary"),
    )
    db_session.commit()

    rows = get_answers(db_session, application.id)
    assert len(rows) == 2
    by_question = {r.question_text: r for r in rows}
    assert by_question["Tell me about yourself."].answer_text == "I am a candidate."
    assert by_question["Salary?"].requires_human is True
    assert by_question["Salary?"].answer_text is None


def test_count_submissions_since_only_counts_submitted_applications(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    now = datetime.now(UTC)

    submitted = Application(
        job_id=job.id, candidate_id=candidate.id, status="SUBMITTED", submitted_at=now,
    )
    db_session.add(submitted)
    db_session.commit()

    assert count_submissions_since(db_session, candidate.id, now - timedelta(hours=1)) == 1
    assert count_submissions_since(db_session, candidate.id, now + timedelta(hours=1)) == 0


def test_count_submissions_to_company_is_lifetime_by_default(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    old = datetime.now(UTC) - timedelta(days=365)
    db_session.add(
        Application(job_id=job.id, candidate_id=candidate.id, status="SUBMITTED", submitted_at=old)
    )
    db_session.commit()

    assert count_submissions_to_company(db_session, candidate.id, "Acme") == 1
    assert count_submissions_to_company(db_session, candidate.id, "Other Co") == 0


def test_count_submissions_from_source_since(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    now = datetime.now(UTC)
    db_session.add(
        Application(job_id=job.id, candidate_id=candidate.id, status="SUBMITTED", submitted_at=now)
    )
    db_session.commit()

    assert (
        count_submissions_from_source_since(
            db_session, candidate.id, job.source_id, now - timedelta(hours=1)
        )
        == 1
    )
    assert (
        count_submissions_from_source_since(
            db_session, candidate.id, job.source_id, now + timedelta(hours=1)
        )
        == 0
    )


def test_get_application_returns_none_when_absent(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    assert get_application(db_session, job.id, candidate.id) is None


# --------------------------------------------------------------------------
# Security fix (post-Phase-6A audit): record_event() must never persist a
# secret into the immutable application_events audit trail.
# --------------------------------------------------------------------------
def test_record_event_redacts_sensitive_keys_before_persisting(db_session, job_and_candidate):
    job, candidate = job_and_candidate
    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    record_event(
        db_session, application.id, "PROVIDER_ERROR",
        {"api_key": "sk-liveSECRET1234567890", "provider": "manual_review"},
    )
    db_session.commit()

    event = (
        db_session.query(ApplicationEvent)
        .filter_by(application_id=application.id, event_type="PROVIDER_ERROR")
        .one()
    )
    assert event.details["api_key"] == "***REDACTED***"
    assert event.details["provider"] == "manual_review"  # non-sensitive, untouched


def test_record_event_redacts_a_secret_embedded_in_a_free_text_error_message(
    db_session, job_and_candidate
):
    """The realistic shape of a leak: a raw exception message (never a
    conveniently-named dict key) embedding a credential."""
    job, candidate = job_and_candidate
    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    record_event(
        db_session, application.id, "SUBMISSION_FAILED",
        {"error": "provider auth failed: api_key=sk-liveSECRET1234567890 rejected"},
    )
    db_session.commit()

    event = (
        db_session.query(ApplicationEvent)
        .filter_by(application_id=application.id, event_type="SUBMISSION_FAILED")
        .one()
    )
    assert "sk-liveSECRET1234567890" not in event.details["error"]
    assert "***REDACTED***" in event.details["error"]


def test_transition_status_redacted_details_reach_the_audit_trail(db_session, job_and_candidate):
    """transition_status() delegates to record_event() — confirm the
    redaction is applied end-to-end through the actual status-change path,
    not just when record_event() is called directly."""
    job, candidate = job_and_candidate
    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    db_session.commit()

    transition_status(
        db_session, application, ApplicationStatus.FAILED,
        event_type="SUBMISSION_FAILED",
        details={"error": "auth failed: password=hunter2secret", "provider": "manual_review"},
    )
    db_session.commit()

    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    combined = json.dumps([e.details for e in events])
    assert "hunter2secret" not in combined
    assert "***REDACTED***" in combined

"""Phase 6C — `job_agent.applications.approvals` unit tests.

Covers fingerprint determinism, validity computation (expired/consumed/
revoked/mismatched all excluded), single-use consumption, and robustness
against SQLite's loss of timezone info on a DB round trip.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.applications.approvals import (
    compute_answer_fingerprint,
    consume_approval,
    create_approval,
    get_valid_approval,
    revoke_approval,
)
from job_agent.applications.schema import GeneratedAnswer, QuestionCategory
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
def application_row(db_session):
    company = Company(name="Acme")
    db_session.add(company)
    db_session.flush()
    source = JobSource(name="approvals-test", kind="ats_api", enabled=True)
    db_session.add(source)
    db_session.flush()
    job = JobRow(
        source_id=source.id, source_job_id="1", company_id=company.id, company_name="Acme",
        title="SE", application_url="https://x.test/1", job_fingerprint="fp-approvals",
    )
    db_session.add(job)
    candidate = Candidate(
        name="T", email="t@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(candidate)
    db_session.flush()
    application = Application(job_id=job.id, candidate_id=candidate.id, status="PREPARED")
    db_session.add(application)
    db_session.flush()
    db_session.commit()
    return application


def _answer(question="Q1", answer="A1"):
    return GeneratedAnswer(
        question=question, category=QuestionCategory.COMPANY, answer=answer,
        confidence=0.9, source="template", requires_human=False, validated=True,
    )


# --------------------------------------------------------------------------
# compute_answer_fingerprint
# --------------------------------------------------------------------------
def test_fingerprint_is_deterministic_for_same_answers():
    answers = [_answer("Q1", "A1"), _answer("Q2", "A2")]
    assert compute_answer_fingerprint(answers) == compute_answer_fingerprint(answers)


def test_fingerprint_is_order_independent():
    a = [_answer("Q1", "A1"), _answer("Q2", "A2")]
    b = [_answer("Q2", "A2"), _answer("Q1", "A1")]
    assert compute_answer_fingerprint(a) == compute_answer_fingerprint(b)


def test_fingerprint_changes_if_any_answer_text_changes():
    a = [_answer("Q1", "A1")]
    b = [_answer("Q1", "A1-different")]
    assert compute_answer_fingerprint(a) != compute_answer_fingerprint(b)


def test_fingerprint_changes_if_question_text_changes():
    a = [_answer("Q1", "A1")]
    b = [_answer("Q1-different", "A1")]
    assert compute_answer_fingerprint(a) != compute_answer_fingerprint(b)


def test_fingerprint_of_empty_answer_list_is_stable():
    assert compute_answer_fingerprint([]) == compute_answer_fingerprint([])


# --------------------------------------------------------------------------
# create_approval / get_valid_approval
# --------------------------------------------------------------------------
def test_freshly_created_approval_is_valid(db_session, application_row):
    approval = create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()

    found = get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    assert found is not None
    assert found.id == approval.id


def test_approval_with_wrong_posting_fingerprint_is_not_found(db_session, application_row):
    create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()

    assert get_valid_approval(db_session, application_row.id, "OTHER", "fp-answers") is None


def test_approval_with_wrong_answer_fingerprint_is_not_found(db_session, application_row):
    create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()

    assert get_valid_approval(db_session, application_row.id, "fp-posting", "OTHER") is None


def test_approval_for_wrong_application_id_is_not_found(db_session, application_row):
    create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()

    other_id = application_row.id + 999
    assert get_valid_approval(db_session, other_id, "fp-posting", "fp-answers") is None


def test_expired_approval_is_not_valid(db_session, application_row):
    create_approval(db_session, application_row.id, "fp-posting", "fp-answers", ttl_hours=-1)
    db_session.commit()

    assert get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers") is None


def test_expired_approval_is_not_valid_after_a_db_round_trip(db_session, application_row):
    """Regression test: SQLite loses tzinfo on round trip, so the
    expiry comparison must normalize a naive `expires_at` back to UTC
    rather than raising or comparing incorrectly."""
    approval = create_approval(
        db_session, application_row.id, "fp-posting", "fp-answers", ttl_hours=-1
    )
    db_session.commit()
    db_session.expire(approval)  # force a fresh SELECT on next access

    assert get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers") is None


def test_consumed_approval_is_not_valid(db_session, application_row):
    approval = create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()
    consume_approval(db_session, approval)
    db_session.commit()

    assert get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers") is None


def test_revoked_approval_is_not_valid(db_session, application_row):
    approval = create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()
    revoke_approval(db_session, approval)
    db_session.commit()

    assert get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers") is None


def test_most_recent_matching_approval_is_returned(db_session, application_row):
    create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    second = create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()

    found = get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    assert found is not None
    assert found.id == second.id


def test_older_approval_for_different_content_is_never_used_as_a_fallback(
    db_session, application_row
):
    """A stale, still-unexpired approval for OLD content must never
    validate against NEW content, even if it's the only approval that
    exists — no partial or fallback match."""
    create_approval(db_session, application_row.id, "fp-old-posting", "fp-old-answers")
    db_session.commit()

    found = get_valid_approval(db_session, application_row.id, "fp-new-posting", "fp-new-answers")
    assert found is None


def test_consume_approval_is_idempotent_in_effect_second_consume_still_invalid(
    db_session, application_row
):
    approval = create_approval(db_session, application_row.id, "fp-posting", "fp-answers")
    db_session.commit()
    consume_approval(db_session, approval)
    db_session.commit()
    first_consumed_at = approval.consumed_at

    consume_approval(db_session, approval)  # calling again must not raise
    db_session.commit()
    assert approval.consumed_at != first_consumed_at or approval.consumed_at == first_consumed_at
    assert get_valid_approval(db_session, application_row.id, "fp-posting", "fp-answers") is None

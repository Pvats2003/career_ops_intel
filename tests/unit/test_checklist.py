"""Application checklist — Career OS FINAL GOD MODE Part 4.12. Every item
must come from real stored data or an explicit manual toggle — never a
guess about work the candidate may or may not have actually done."""

from __future__ import annotations

from job_agent.applications.checklist import compute_checklist
from job_agent.db.models import Application, Resume


def _application(**overrides) -> Application:
    base = dict(
        job_id=1,
        candidate_id=1,
        resume_id=None,
        status="DISCOVERED",
        pipeline_stage="SAVED",
        cover_letter_ready=False,
        questions_prepared=False,
    )
    base.update(overrides)
    return Application(**base)


def _resume(**overrides) -> Resume:
    base = dict(candidate_id=1, variant_name="master", file_path="/tmp/resume.docx")
    base.update(overrides)
    return Resume(**base)


def test_fresh_application_has_nothing_checked():
    checklist = compute_checklist(_application(), None)
    assert checklist == compute_checklist(_application(), None)
    assert not checklist.resume_selected
    assert not checklist.resume_tailored
    assert not checklist.cover_letter_ready
    assert not checklist.questions_prepared
    assert not checklist.submitted
    assert not checklist.confirmation_received


def test_resume_selected_without_tailoring():
    checklist = compute_checklist(_application(resume_id=1), _resume(is_tailored=False))
    assert checklist.resume_selected
    assert not checklist.resume_tailored


def test_resume_selected_and_tailored():
    checklist = compute_checklist(_application(resume_id=1), _resume(is_tailored=True))
    assert checklist.resume_selected
    assert checklist.resume_tailored


def test_manual_toggles_reflected_directly():
    checklist = compute_checklist(
        _application(cover_letter_ready=True, questions_prepared=True), None
    )
    assert checklist.cover_letter_ready
    assert checklist.questions_prepared


def test_submitted_via_status():
    checklist = compute_checklist(_application(status="SUBMITTED"), None)
    assert checklist.submitted


def test_submitted_via_submitted_at_timestamp():
    from datetime import UTC, datetime

    checklist = compute_checklist(_application(submitted_at=datetime.now(UTC)), None)
    assert checklist.submitted


def test_submitted_via_pipeline_stage_applied():
    checklist = compute_checklist(_application(pipeline_stage="APPLIED"), None)
    assert checklist.submitted


def test_not_submitted_while_only_saved_or_shortlisted():
    assert not compute_checklist(_application(pipeline_stage="SAVED"), None).submitted
    assert not compute_checklist(_application(pipeline_stage="SHORTLISTED"), None).submitted


def test_confirmation_received_from_confirmation_id():
    checklist = compute_checklist(_application(confirmation_id="conf-123"), None)
    assert checklist.confirmation_received


def test_confirmation_received_from_confirmation_url():
    checklist = compute_checklist(
        _application(confirmation_url="https://example.test/confirm/1"), None
    )
    assert checklist.confirmation_received

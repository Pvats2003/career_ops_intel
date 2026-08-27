from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_agent.applications.schema import (
    ApplicationInspection,
    ApplicationStatus,
    ApplicationTarget,
    GeneratedAnswer,
    PreparedFormState,
    QuestionCategory,
    SubmissionEvidence,
)


def test_generated_answer_requires_human_true_forbids_answer_value():
    with pytest.raises(ValidationError):
        GeneratedAnswer(
            question="q", category=QuestionCategory.SALARY, answer="50000",
            confidence=0.9, source="x", requires_human=True, validated=True,
        )


def test_generated_answer_requires_human_false_requires_answer_value():
    with pytest.raises(ValidationError):
        GeneratedAnswer(
            question="q", category=QuestionCategory.MOTIVATION, answer=None,
            confidence=0.9, source="x", requires_human=False, validated=True,
        )


def test_generated_answer_valid_human_required_case():
    answer = GeneratedAnswer(
        question="q", category=QuestionCategory.SALARY, answer=None,
        confidence=0.0, source="hard_block:SALARY", requires_human=True, validated=True,
    )
    assert answer.answer is None


def test_generated_answer_valid_answerable_case():
    answer = GeneratedAnswer(
        question="q", category=QuestionCategory.MOTIVATION, answer="Truthful answer.",
        confidence=0.9, source="answer_bank:x", requires_human=False, validated=True,
    )
    assert answer.answer == "Truthful answer."


def test_submission_evidence_has_concrete_evidence_true_with_any_field():
    assert SubmissionEvidence(confirmation_id="ABC").has_concrete_evidence is True
    assert SubmissionEvidence(confirmation_url="https://x.test").has_concrete_evidence is True
    assert SubmissionEvidence(confirmation_text="thanks!").has_concrete_evidence is True
    assert SubmissionEvidence(screenshot_path="/tmp/x.png").has_concrete_evidence is True


def test_submission_evidence_has_concrete_evidence_false_when_empty():
    assert SubmissionEvidence().has_concrete_evidence is False


def test_submission_evidence_whitespace_only_fields_do_not_count_as_evidence():
    """A provider returning blank/whitespace strings must not be trusted as
    real confirmation — this is exactly the loophole a buggy or dishonest
    provider could use to fake `has_concrete_evidence`."""
    assert SubmissionEvidence(confirmation_id="   ").has_concrete_evidence is False
    assert SubmissionEvidence(confirmation_text="\n\t").has_concrete_evidence is False


# --------------------------------------------------------------------------
# Phase 6A contract types
# --------------------------------------------------------------------------
def test_submission_uncertain_is_a_valid_application_status():
    assert ApplicationStatus.SUBMISSION_UNCERTAIN.value == "SUBMISSION_UNCERTAIN"


def test_application_target_defaults_are_conservative():
    """No provider_reference/detail supplied — a target constructed with
    minimal fields must not silently claim reachability."""
    target = ApplicationTarget(job_id=1, reachable=False)
    assert target.provider_reference is None
    assert target.detail == ""


def test_application_target_is_frozen():
    target = ApplicationTarget(job_id=1, reachable=True)
    with pytest.raises(ValidationError):
        target.reachable = False  # type: ignore[misc]


def test_application_inspection_defaults_are_all_false():
    """Every boolean facet defaults to False/unset except
    structure_recognized, which must be supplied explicitly — there is no
    default that silently claims the form was understood."""
    inspection = ApplicationInspection(structure_recognized=False)
    assert inspection.captcha_detected is False
    assert inspection.mfa_detected is False
    assert inspection.consent_required is False


def test_application_inspection_can_report_all_hazards_at_once():
    inspection = ApplicationInspection(
        structure_recognized=True, captcha_detected=True, mfa_detected=True,
        consent_required=True, detail="all hazards present",
    )
    assert inspection.captcha_detected is True
    assert inspection.mfa_detected is True
    assert inspection.consent_required is True


def test_prepared_form_state_records_answer_count_not_content():
    """PreparedFormState is deliberately an opaque handle — it must never
    carry the actual answer text, only a count, so filling and submitting
    stay separately-audited without duplicating candidate data."""
    state = PreparedFormState(target_job_id=1, answer_count=3)
    assert state.answer_count == 3
    assert not hasattr(state, "answers")

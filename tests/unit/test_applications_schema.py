from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_agent.applications.schema import GeneratedAnswer, QuestionCategory, SubmissionEvidence


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

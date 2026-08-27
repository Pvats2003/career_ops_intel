from __future__ import annotations

import pytest

from job_agent.applications.answer_validator import validate_generated_answer
from job_agent.resume.extractor import extract_resume_text


@pytest.fixture(scope="session")
def resume_text(repo_root):
    return extract_resume_text(repo_root / "candidate" / "resume_master.docx")


def test_truthful_answer_passes(real_profile, resume_text):
    answer = "I built an OCR tool using Claude Vision at Instawork Robotics Labs."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is True
    assert result.unverifiable_claims == ()


def test_fabricated_employer_is_caught(real_profile, resume_text):
    answer = "I previously worked at Morgan Stanley as a senior analyst."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is False
    assert "Morgan Stanley" in result.unverifiable_claims


def test_fabricated_metric_is_caught(real_profile, resume_text):
    answer = "I increased team velocity by 47 percent in my last role."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is False
    assert "47" in result.unverifiable_claims


def test_real_metric_from_resume_passes(real_profile, resume_text):
    answer = "I produced a field recording guide covering 116 businesses."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is True


def test_generic_language_has_nothing_to_flag(real_profile, resume_text):
    answer = "I am a hardworking, detail-oriented person who loves solving problems."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is True


def test_common_allowlisted_phrases_do_not_false_positive(real_profile, resume_text):
    answer = "I am excited about this role and would be a great addition to the team."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is True


def test_single_digit_numbers_are_not_flagged():
    """Team-size-style small numbers are too generic to usefully check
    either way — flagging them would create noisy false positives."""
    from job_agent.applications.answer_validator import _NUMBER_PATTERN

    assert _NUMBER_PATTERN.findall("I led a team of 5 people.") == []


def test_multiple_unverifiable_claims_all_reported(real_profile, resume_text):
    answer = "At Wayne Enterprises I grew revenue by 92 percent using Docker and Kubernetes."
    result = validate_generated_answer(answer, real_profile, resume_text)
    assert result.passed is False
    assert "Wayne Enterprises" in result.unverifiable_claims
    assert "92" in result.unverifiable_claims

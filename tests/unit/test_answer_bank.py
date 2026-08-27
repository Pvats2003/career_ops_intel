from __future__ import annotations

import pytest

from job_agent.applications.answer_bank import (
    AnswerBankParseError,
    load_answer_bank,
    match_slug,
)
from job_agent.applications.schema import QuestionCategory


@pytest.fixture(scope="session")
def bank(real_config):
    return load_answer_bank(real_config.env.candidate_dir / "answers")


def test_loads_every_real_bank_entry(bank):
    assert len(bank) == 8
    slugs = {e.slug for e in bank}
    assert "tell_me_about_yourself" in slugs
    assert "why_this_company" in slugs
    assert "salary_expectations" in slugs


def test_requires_human_flags_match_real_content(bank):
    by_slug = {e.slug: e for e in bank}
    assert by_slug["why_this_company"].requires_human is True
    assert by_slug["salary_expectations"].requires_human is True
    assert by_slug["failure"].requires_human is True
    assert by_slug["tell_me_about_yourself"].requires_human is False
    assert by_slug["strengths"].requires_human is False


def test_categories_parsed_correctly(bank):
    by_slug = {e.slug: e for e in bank}
    assert by_slug["why_this_company"].category == QuestionCategory.COMPANY
    assert by_slug["salary_expectations"].category == QuestionCategory.SALARY
    assert by_slug["why_this_role"].category == QuestionCategory.ROLE


def test_bodies_are_nonempty_and_trimmed(bank):
    for entry in bank:
        assert entry.body
        assert entry.body == entry.body.strip()


@pytest.mark.parametrize(
    ("question", "expected_slug"),
    [
        ("Tell me about yourself.", "tell_me_about_yourself"),
        ("Why do you want to work here?", "why_this_company"),
        ("Why are you a good fit for this role?", "why_this_role"),
        ("What is your greatest strength?", "strengths"),
        ("What are your salary expectations for this position?", "salary_expectations"),
        ("Describe your biggest achievement.", "biggest_achievement"),
    ],
)
def test_match_slug_finds_correct_entry(question, expected_slug):
    assert match_slug(question) == expected_slug


def test_match_slug_returns_none_for_unrelated_question():
    assert match_slug("What is your favorite color of paperclip?") is None


def test_missing_separator_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("question_type: MOTIVATION\nrequires_human: false\nNo separator here.")
    with pytest.raises(AnswerBankParseError, match="separator"):
        load_answer_bank(tmp_path)


def test_missing_question_type_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("requires_human: false\n---\nbody")
    with pytest.raises(AnswerBankParseError, match="question_type"):
        load_answer_bank(tmp_path)


def test_unknown_question_type_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("question_type: NOT_A_REAL_CATEGORY\nrequires_human: false\n---\nbody")
    with pytest.raises(AnswerBankParseError, match="unknown question_type"):
        load_answer_bank(tmp_path)

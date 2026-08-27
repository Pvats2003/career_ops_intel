from __future__ import annotations

from job_agent.matching.text import (
    any_keyword_present,
    contains_keyword,
    extract_year_requirement,
    normalize,
)


def test_normalize_strips_punctuation_and_case():
    assert normalize("A/B Testing!") == "a b testing"


def test_contains_keyword_word_boundary():
    assert contains_keyword("We use SQL every day", "SQL")
    assert not contains_keyword("We use MySQL every day", "SQL")


def test_contains_keyword_multiword():
    assert contains_keyword("Own the product roadmap end to end", "product roadmap")


def test_contains_keyword_handles_punctuation_in_keyword():
    assert contains_keyword("Familiar with A/B testing methods", "A/B testing")


def test_contains_keyword_empty_inputs():
    assert not contains_keyword("", "SQL")
    assert not contains_keyword("some text", "")


def test_any_keyword_present():
    hits = any_keyword_present("SQL and Excel required", ("SQL", "Excel", "Tableau"))
    assert hits == ["SQL", "Excel"]


def test_extract_year_requirement_takes_max():
    assert extract_year_requirement("2+ years preferred, 5+ years for senior track") == 5


def test_extract_year_requirement_none_when_absent():
    assert extract_year_requirement("No specific experience requirement") is None


def test_extract_year_requirement_ignores_noise():
    assert extract_year_requirement("founded in 1999, growing fast") is None

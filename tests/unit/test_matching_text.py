from __future__ import annotations

from job_agent.matching.text import (
    any_keyword_present,
    contains_keyword,
    contains_keyword_or_synonym,
    extract_year_requirement,
    fuzzy_overlap,
    fuzzy_overlap_with_synonyms,
    keyword_synonyms,
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


# --- Matching Engine V3 calibration fix A: ranges resolve to their LOWER
# bound ("0-2 years" means 0 is enough), not their upper one. -------------


def test_extract_year_requirement_range_zero_to_two():
    assert extract_year_requirement("0-2 years") == 0


def test_extract_year_requirement_range_one_to_three():
    assert extract_year_requirement("1-3 years") == 1


def test_extract_year_requirement_range_three_to_five():
    assert extract_year_requirement("3-5 years") == 3


def test_extract_year_requirement_plain_plus():
    assert extract_year_requirement("5+ years") == 5


def test_extract_year_requirement_plain_number():
    assert extract_year_requirement("5 years") == 5


def test_extract_year_requirement_at_least_prose():
    assert extract_year_requirement("Must have at least 3 years of experience") == 3


def test_extract_year_requirement_minimum_prose():
    assert extract_year_requirement("Minimum 3 years required") == 3
    assert extract_year_requirement("Minimum of 3 years required") == 3


def test_extract_year_requirement_or_more_prose():
    assert extract_year_requirement("3 or more years of relevant work") == 3


def test_extract_year_requirement_en_dash_range():
    assert extract_year_requirement("2–4 years") == 2


def test_extract_year_requirement_to_range():
    assert extract_year_requirement("2 to 4 years") == 2


def test_extract_year_requirement_range_with_trailing_plus():
    assert extract_year_requirement("2-4+ years") == 2


def test_extract_year_requirement_range_in_full_sentence():
    """The realistic phrasing this fix exists for — an early-career
    posting stating a range, not a single number."""
    assert extract_year_requirement("We're looking for someone with 0-2 years of experience.") == 0


def test_extract_year_requirement_does_not_misread_calendar_years():
    assert extract_year_requirement("Founded in 2015, hiring for 2026") is None
    assert extract_year_requirement("B.Tech, graduating May 2026") is None


def test_extract_year_requirement_does_not_misread_salary_or_percentages():
    assert extract_year_requirement("Salary: $80,000-100,000 annually") is None
    assert extract_year_requirement("Requires 50-75% travel") is None


def test_extract_year_requirement_does_not_misread_job_ids():
    assert extract_year_requirement("Job ID: 2024-5567") is None


# --- fuzzy_overlap: real-world activation audit finding -------------------
# A candidate's authored skill name ("Basic SQL") is a qualified version of
# the bare vocabulary term a job posting uses ("SQL") — matching.
# deterministic._find_evidence and resume.tailor's skill-relevance checks
# both need this to still count as a match, not "missing".


def test_fuzzy_overlap_matches_qualified_skill_name():
    assert fuzzy_overlap("SQL", "Basic SQL") is True
    assert fuzzy_overlap("Basic SQL", "SQL") is True


def test_fuzzy_overlap_matches_parenthetical_qualifier():
    assert fuzzy_overlap("Figma", "Figma (basic)") is True


def test_fuzzy_overlap_false_for_unrelated_terms():
    assert fuzzy_overlap("SQL", "Excel") is False


def test_fuzzy_overlap_empty_inputs():
    assert fuzzy_overlap("", "SQL") is False
    assert fuzzy_overlap("SQL", "") is False


# --- Matching Engine V3 calibration fix D: a small, explicit synonym
# layer for a handful of recurring word-order/inflection mismatches. -----


def test_keyword_synonyms_includes_itself():
    assert "SQL" in keyword_synonyms("SQL")


def test_keyword_synonyms_unrelated_term_has_no_extra_forms():
    assert keyword_synonyms("Tableau") == frozenset({"Tableau"})


def test_keyword_synonyms_roadmap_group():
    forms = keyword_synonyms("product roadmap")
    assert "roadmapping" in {f.lower() for f in forms}
    assert "roadmap" in {f.lower() for f in forms}


def test_contains_keyword_or_synonym_positive_roadmapping():
    """The candidate's skill "Roadmapping" and the vocabulary phrase
    "product roadmap" are the same concept, word-order/inflection aside."""
    assert contains_keyword_or_synonym("Own the roadmapping process", "product roadmap")
    assert contains_keyword_or_synonym("Own the product roadmap", "roadmapping")


def test_contains_keyword_or_synonym_positive_process_documentation():
    assert contains_keyword_or_synonym(
        "Responsible for documenting processes across teams", "process documentation"
    )
    assert contains_keyword_or_synonym("Must document processes clearly", "process documentation")


def test_contains_keyword_or_synonym_positive_requirements_gathering():
    assert contains_keyword_or_synonym(
        "Skilled at gathering requirements from stakeholders", "requirements gathering"
    )


def test_contains_keyword_or_synonym_positive_stakeholder_communication_plural():
    assert contains_keyword_or_synonym(
        "Strong stakeholder communications across the org", "stakeholder communication"
    )


def test_contains_keyword_or_synonym_positive_backlog_grooming():
    assert contains_keyword_or_synonym("Responsible for grooming the backlog", "backlog grooming")


def test_contains_keyword_or_synonym_negative_unrelated_terms():
    """Synonym expansion must never widen matching to unrelated concepts —
    only the explicitly-curated groups get extra forms, and only to other
    genuine restatements of the SAME activity."""
    assert not contains_keyword_or_synonym("We use Tableau every day", "Power BI")
    assert not contains_keyword_or_synonym("Own the product roadmap", "requirements gathering")
    assert not contains_keyword_or_synonym("Gather requirements from users", "product roadmap")
    assert not contains_keyword_or_synonym("Manage the sales pipeline", "backlog grooming")


def test_fuzzy_overlap_with_synonyms_matches_roadmapping_skill():
    """The exact real-world case this fix exists for: a candidate skill
    authored as "Roadmapping" must count as evidence for the vocabulary
    term "product roadmap"."""
    assert fuzzy_overlap_with_synonyms("product roadmap", "Roadmapping") is True
    assert fuzzy_overlap_with_synonyms("product roadmap", "Roadmapping (HAS)") is True


def test_fuzzy_overlap_with_synonyms_still_false_for_unrelated_skill():
    assert fuzzy_overlap_with_synonyms("product roadmap", "Basic Excel") is False


def test_fuzzy_overlap_with_synonyms_preserves_plain_fuzzy_overlap_behavior():
    """Terms with no defined synonym group behave exactly like plain
    `fuzzy_overlap` — this layer only ever ADDS recognized forms, never
    changes matching for anything outside the curated groups."""
    assert fuzzy_overlap_with_synonyms("SQL", "Basic SQL") is True
    assert fuzzy_overlap_with_synonyms("SQL", "Excel") is False

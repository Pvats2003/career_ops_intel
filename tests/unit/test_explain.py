"""Explainable AI — Career OS FINAL GOD MODE Part 7.21."""

from __future__ import annotations

from job_agent.candidate.explain import explain_ranking
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.matching.ranking import RankedJob


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme",
        title="Business Analyst",
        job_fingerprint="fp",
        freshness_status="NEW",
        lifecycle_status="ACTIVE",
    )
    base.update(overrides)
    return JobRow(**base)


def _match(**overrides) -> JobMatchRow:
    base = dict(
        job_id=1,
        candidate_id=1,
        overall_score=85,
        decision="APPLY",
        reasoning="Strong overlap.",
        missing_requirements=[],
        concerns=[],
        semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def _ranked(**overrides) -> RankedJob:
    base = dict(
        job=_job(),
        match=_match(),
        rank_score=75.0,
        why=("Strong overlap.",),
        gaps=(),
        recommendation="Apply today.",
        components={"match": 38.0, "freshness": 12.0, "career_value": 20.0},
    )
    base.update(overrides)
    return RankedJob(**base)


def test_reasons_are_sorted_by_contribution_descending():
    breakdown = explain_ranking(_ranked())
    assert breakdown.reasons[0].startswith("Candidate fit with your profile contributes 38.0")
    assert breakdown.reasons[1].startswith("Career value")
    assert breakdown.reasons[2].startswith("How recently this was posted")


def test_zero_contribution_components_are_omitted():
    ranked = _ranked(components={"match": 38.0, "company_fit": 0.0})
    breakdown = explain_ranking(ranked)
    assert not any("Company fit" in r for r in breakdown.reasons)


def test_ranked_why_strings_are_appended():
    breakdown = explain_ranking(_ranked(why=("Freshly posted.",)))
    assert "Freshly posted." in breakdown.reasons


def test_main_weakness_from_gaps_when_present():
    breakdown = explain_ranking(_ranked(gaps=("Missing: SQL",)))
    assert breakdown.main_weakness == "Missing: SQL"


def test_main_weakness_falls_back_to_weakest_component_when_no_gaps():
    ranked = _ranked(gaps=(), components={"match": 38.0, "freshness": 2.0, "career_value": 20.0})
    breakdown = explain_ranking(ranked)
    assert breakdown.main_weakness is not None
    assert "recently" in breakdown.main_weakness.lower()
    assert "2.0" in breakdown.main_weakness


def test_no_components_and_no_gaps_gives_no_weakness():
    breakdown = explain_ranking(_ranked(components={}, gaps=()))
    assert breakdown.main_weakness is None


def test_rank_score_passed_through_unchanged():
    breakdown = explain_ranking(_ranked(rank_score=91.3))
    assert breakdown.rank_score == 91.3

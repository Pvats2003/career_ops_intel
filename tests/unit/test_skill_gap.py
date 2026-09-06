"""Skill Gap Intelligence (job_agent.candidate.skill_gap) — CAREER OS
FINAL GOD MODE Part 2.6."""

from __future__ import annotations

from job_agent.candidate.career_paths import CareerPathResult
from job_agent.candidate.skill_gap import discover_skill_gaps
from job_agent.db.models import JobMatch as JobMatchRow


def _match(**overrides) -> JobMatchRow:
    base = dict(
        job_id=1, candidate_id=1, overall_score=80, decision="APPLY",
        reasoning="ok", missing_requirements=[], concerns=[], semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def _path(**overrides) -> CareerPathResult:
    base = dict(
        label="Product Operations", fit_score=90, evidence=(), relevant_skills=(),
        relevant_experience=(), missing_skills=(), typical_titles=(), career_upside="High",
        recommended_priority="HIGH",
    )
    base.update(overrides)
    return CareerPathResult(**base)


def test_below_min_sample_returns_empty():
    matches = [_match(missing_requirements=["SQL"]) for _ in range(2)]
    assert discover_skill_gaps(matches, [], min_sample=3) == []


def test_frequency_counts_and_percentage_are_accurate():
    matches = [_match(missing_requirements=["SQL"]) for _ in range(3)] + [
        _match(missing_requirements=[]) for _ in range(2)
    ]
    entries = discover_skill_gaps(matches, [], min_sample=3)
    sql = next(e for e in entries if e.skill == "SQL")
    assert sql.frequency_count == 3
    assert sql.frequency_pct == 60.0  # 3 of 5 strong matches


def test_only_apply_and_review_decisions_count_as_strong():
    matches = [_match(missing_requirements=["SQL"], decision="APPLY") for _ in range(3)]
    matches += [_match(missing_requirements=["SQL"], decision="SKIP") for _ in range(3)]
    entries = discover_skill_gaps(matches, [], min_sample=3)
    sql = next(e for e in entries if e.skill == "SQL")
    assert sql.frequency_count == 3


def test_unlocks_counts_only_jobs_where_skill_is_the_sole_gap():
    matches = [
        _match(missing_requirements=["SQL"]),
        _match(missing_requirements=["SQL"]),
        _match(missing_requirements=["SQL", "Python"]),
    ]
    entries = discover_skill_gaps(matches, [], min_sample=3)
    sql = next(e for e in entries if e.skill == "SQL")
    assert sql.unlocks_count == 2


def test_relevant_career_paths_cross_referenced_from_missing_skills():
    matches = [_match(missing_requirements=["SQL"]) for _ in range(3)]
    paths = [_path(label="Product Operations", missing_skills=("SQL",))]
    entries = discover_skill_gaps(matches, paths, min_sample=3)
    sql = next(e for e in entries if e.skill == "SQL")
    assert "Product Operations" in sql.relevant_career_paths


def test_results_sorted_by_frequency_descending_and_limited():
    matches = (
        [_match(missing_requirements=["SQL"]) for _ in range(5)]
        + [_match(missing_requirements=["Python"]) for _ in range(2)]
        + [_match(missing_requirements=["R"]) for _ in range(1)]
    )
    entries = discover_skill_gaps(matches, [], min_sample=3, top_n=2)
    assert len(entries) == 2
    assert entries[0].skill == "SQL"


def test_empty_matches_never_crashes():
    assert discover_skill_gaps([], [], min_sample=3) == []

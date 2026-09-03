"""Company fit scoring (job_agent.matching.company_fit) — Career OS Phase
10 section 15."""

from __future__ import annotations

from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.matching.company_fit import compute_company_fit


def _match(**overrides) -> JobMatchRow:
    base = dict(
        job_id=1, candidate_id=1, overall_score=80, decision="APPLY",
        reasoning="Strong overlap.", missing_requirements=[], concerns=[],
        semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def test_no_matches_returns_unknown_never_a_fabricated_placeholder():
    fit, reasons = compute_company_fit([])
    assert fit is None
    assert reasons


def test_high_scoring_apply_decisions_yield_high_fit():
    fit, _ = compute_company_fit([_match(overall_score=95, decision="APPLY")] * 3)
    assert fit is not None
    assert fit >= 80


def test_low_scoring_skip_decisions_yield_low_fit():
    fit, _ = compute_company_fit([_match(overall_score=20, decision="SKIP")] * 3)
    assert fit is not None
    assert fit <= 30


def test_fit_score_always_within_bounds():
    fit, _ = compute_company_fit([_match(overall_score=100, decision="APPLY")])
    assert fit is not None
    assert 0 <= fit <= 100


def test_reasons_mention_apply_count_when_present():
    _, reasons = compute_company_fit(
        [_match(decision="APPLY"), _match(decision="SKIP", overall_score=10)]
    )
    assert any("APPLY" in r for r in reasons)

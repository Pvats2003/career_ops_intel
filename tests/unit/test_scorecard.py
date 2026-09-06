"""Application scorecard — Career OS FINAL GOD MODE Part 4.11. Every
sub-score must be traceable to the match/confidence/viability modules it
reuses — never a second, independent judgment about the job."""

from __future__ import annotations

from datetime import datetime

from job_agent.applications.scorecard import compute_scorecard
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme",
        title="Business Analyst",
        application_url="https://example.test/apply",
        job_fingerprint="fp",
        freshness_status="NEW",
        lifecycle_status="ACTIVE",
        salary_min=80000,
        salary_max=110000,
        company_id=7,
        posted_at=datetime(2026, 9, 1),
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
        hard_stop_reasons=[],
        location_match=90.0,
        semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def test_strong_job_scores_high_and_recommends_apply():
    scorecard = compute_scorecard(_job(), _match())
    assert scorecard.candidate_fit == 85.0
    assert scorecard.job_quality == 100.0
    assert scorecard.career_value == 100.0
    assert scorecard.application_viability == 100.0
    assert scorecard.overall_score > 80
    assert "Apply" in scorecard.overall_recommendation


def test_no_match_yet_scores_zero_fit_and_says_so():
    scorecard = compute_scorecard(_job(), None)
    assert scorecard.candidate_fit == 0.0
    assert scorecard.career_value == 0.0
    assert "not yet matched" in scorecard.overall_recommendation.lower()


def test_low_data_confidence_lowers_job_quality():
    job = _job(
        salary_min=None, salary_max=None, posted_at=None, freshness_status="UNKNOWN_POST_DATE"
    )
    scorecard = compute_scorecard(job, _match())
    assert scorecard.job_quality == 60.0


def test_blocked_viability_zeroes_that_dimension_and_overrides_recommendation():
    job = _job(application_url=None)
    scorecard = compute_scorecard(job, _match())
    assert scorecard.application_viability == 0.0
    assert "blocker" in scorecard.overall_recommendation.lower()


def test_skip_decision_zeroes_career_value():
    scorecard = compute_scorecard(_job(), _match(decision="SKIP", overall_score=20))
    assert scorecard.career_value == 0.0


def test_overall_score_is_bounded_0_to_100():
    strong = compute_scorecard(_job(), _match(overall_score=100))
    weak = compute_scorecard(
        _job(application_url=None, salary_min=None, salary_max=None),
        _match(decision="SKIP", overall_score=0),
    )
    assert 0.0 <= weak.overall_score <= strong.overall_score <= 100.0

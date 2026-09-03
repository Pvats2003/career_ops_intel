"""Opportunity ranking (job_agent.matching.ranking) — Today's Top 10 /
Apply Now (Career OS Phase 8 sections 9-10)."""

from __future__ import annotations

from job_agent.config.models import PriorityWeights
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.matching.ranking import explain, rank_jobs, rank_score

WEIGHTS = PriorityWeights()  # default: match .5, freshness .2, career .15, company .1, ease .05


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme", title="Business Analyst",
        application_url="https://example.test/apply",
        job_fingerprint="fp", freshness_status="NEW", lifecycle_status="ACTIVE",
    )
    base.update(overrides)
    return JobRow(**base)


def _match(**overrides) -> JobMatchRow:
    base = dict(
        job_id=1, candidate_id=1, overall_score=80, decision="APPLY",
        reasoning="Strong overlap.", missing_requirements=[], concerns=[],
        semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def test_higher_match_score_ranks_higher():
    low = rank_score(_job(), _match(overall_score=40, decision="SAVE"), WEIGHTS)
    high = rank_score(_job(), _match(overall_score=95, decision="APPLY"), WEIGHTS)
    assert high > low


def test_fresher_job_ranks_higher_at_equal_match():
    stale = rank_score(_job(freshness_status="OLD"), _match(), WEIGHTS)
    fresh = rank_score(_job(freshness_status="JUST_POSTED"), _match(), WEIGHTS)
    assert fresh > stale


def test_job_with_no_application_url_ranks_lower():
    with_link = rank_score(_job(application_url="https://x.test"), _match(), WEIGHTS)
    without_link = rank_score(_job(application_url=None), _match(), WEIGHTS)
    assert with_link > without_link


def test_no_match_at_all_still_produces_a_score_never_crashes():
    score = rank_score(_job(), None, WEIGHTS)
    assert score >= 0


def test_rank_jobs_excludes_inactive_lifecycle():
    active = _job(job_fingerprint="a", lifecycle_status="ACTIVE")
    closed = _job(job_fingerprint="b", lifecycle_status="CLOSED")
    ranked = rank_jobs([(active, _match()), (closed, _match())], WEIGHTS)
    assert len(ranked) == 1
    assert ranked[0].job is active


def test_rank_jobs_sorted_descending():
    weak = _job(job_fingerprint="weak")
    strong = _job(job_fingerprint="strong")
    ranked = rank_jobs(
        [
            (weak, _match(overall_score=20, decision="SKIP")),
            (strong, _match(overall_score=98, decision="APPLY")),
        ],
        WEIGHTS,
    )
    assert ranked[0].job is strong
    assert ranked[0].rank_score >= ranked[1].rank_score


def test_rank_jobs_respects_limit():
    jobs = [(_job(job_fingerprint=str(i)), _match()) for i in range(5)]
    ranked = rank_jobs(jobs, WEIGHTS, limit=2)
    assert len(ranked) == 2


def test_explain_grounds_why_and_gaps_in_the_actual_match_never_invents():
    job = _job()
    match = _match(
        reasoning="Matches your operations background.",
        missing_requirements=["SQL"], concerns=["Requires 2+ years"],
    )
    why, gaps, recommendation = explain(job, match)
    assert "Matches your operations background." in why
    assert "SQL" in gaps
    assert "Requires 2+ years" in gaps
    assert recommendation == "Apply today."


def test_explain_with_no_match_never_crashes_and_recommends_low_priority():
    why, gaps, recommendation = explain(_job(), None)
    assert recommendation == "Lower priority for now."


def test_explain_flags_missing_application_url_as_a_gap():
    _, gaps, _ = explain(_job(application_url=None), _match())
    assert any("application link" in g.lower() for g in gaps)

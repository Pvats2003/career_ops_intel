"""Morning briefing (job_agent.candidate.briefing) — CAREER OS FINAL GOD
MODE Part 1.3."""

from __future__ import annotations

from job_agent.applications.follow_up import FollowUpRecommendation
from job_agent.candidate.briefing import compose_morning_briefing
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.matching.ranking import RankedJob


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme", title="Business Analyst", location="Remote",
        job_fingerprint="fp", freshness_status="NEW",
    )
    base.update(overrides)
    return JobRow(**base)


def _match(**overrides) -> JobMatchRow:
    base = dict(
        job_id=1, candidate_id=1, overall_score=90, decision="APPLY",
        reasoning="Strong overlap.", missing_requirements=[], concerns=[],
        semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def _ranked(job, match, *, rank_score=90.0, why=("Strong overlap.",)):
    return RankedJob(
        job=job, match=match, rank_score=rank_score, why=why, gaps=(),
        recommendation="Apply today.",
    )


def _follow_up(**overrides) -> FollowUpRecommendation:
    base = dict(
        application=ApplicationRow(
            id=1, job_id=1, candidate_id=1, status="SUBMITTED", pipeline_stage="APPLIED"
        ),
        job=_job(),
        applied_days_ago=9,
        suggested_action="Follow up now.",
    )
    base.update(overrides)
    return FollowUpRecommendation(**base)


def test_counts_by_decision_tier():
    ranked = [
        _ranked(_job(job_fingerprint="a"), _match(decision="APPLY")),
        _ranked(_job(job_fingerprint="b"), _match(decision="REVIEW")),
        _ranked(_job(job_fingerprint="c"), _match(decision="REVIEW")),
        _ranked(_job(job_fingerprint="d"), _match(decision="SAVE")),
        _ranked(_job(job_fingerprint="e"), _match(decision="SKIP")),
    ]
    briefing = compose_morning_briefing(ranked, [])
    assert briefing.exceptional_count == 1
    assert briefing.strong_count == 2
    assert briefing.possible_count == 1
    assert briefing.total_opportunities == 4  # SKIP never counts as "worth attention"


def test_top_highlights_respects_limit_and_order():
    ranked = [
        _ranked(_job(job_fingerprint=str(i)), _match(), rank_score=float(100 - i))
        for i in range(5)
    ]
    briefing = compose_morning_briefing(ranked, [], top_n_highlights=3)
    assert len(briefing.top_highlights) == 3
    assert briefing.top_highlights[0].rank_score == 100.0


def test_highlight_why_grounded_in_ranked_job_not_invented():
    ranked = [_ranked(_job(), _match(), why=("Matches your operations background.",))]
    briefing = compose_morning_briefing(ranked, [])
    assert briefing.top_highlights[0].why == "Matches your operations background."


def test_highlight_why_none_when_ranked_job_has_none():
    ranked = [_ranked(_job(), _match(), why=())]
    briefing = compose_morning_briefing(ranked, [])
    assert briefing.top_highlights[0].why is None


def test_follow_up_summaries_grounded_in_real_follow_ups():
    follow_ups = [_follow_up(applied_days_ago=9), _follow_up(applied_days_ago=14)]
    briefing = compose_morning_briefing([], follow_ups)
    assert len(briefing.follow_up_summaries) == 2
    assert "9 days" in briefing.follow_up_summaries[0]


def test_no_insight_sentences_yields_none_never_invented():
    briefing = compose_morning_briefing([], [])
    assert briefing.career_insight is None


def test_insight_sentence_passed_through_verbatim():
    briefing = compose_morning_briefing([], [], insight_sentences=["SQL appears often."])
    assert briefing.career_insight == "SQL appears often."


def test_no_career_path_yields_no_recommendation():
    briefing = compose_morning_briefing([], [])
    assert briefing.recommendation is None


def test_recommendation_grounded_in_top_career_path_label():
    briefing = compose_morning_briefing([], [], top_career_path_label="Product Operations")
    assert briefing.recommendation == "Prioritize Product Operations this week."


def test_empty_input_never_crashes():
    briefing = compose_morning_briefing([], [])
    assert briefing.total_opportunities == 0
    assert briefing.top_highlights == ()
    assert briefing.follow_up_summaries == ()

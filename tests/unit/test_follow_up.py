"""Follow-up intelligence (job_agent.applications.follow_up) — Career OS
Phase 13."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_agent.applications.follow_up import compute_follow_up_recommendations
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow


def _job(**overrides) -> JobRow:
    base = dict(company_name="Acme", title="Business Analyst", job_fingerprint="fp")
    base.update(overrides)
    return JobRow(**base)


def _application(*, pipeline_stage: str, days_ago: int, **overrides) -> ApplicationRow:
    base = dict(
        job_id=1, candidate_id=1, status="SUBMITTED", pipeline_stage=pipeline_stage,
        updated_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    base.update(overrides)
    return ApplicationRow(**base)


def test_stale_applied_application_surfaces_follow_up():
    app = _application(pipeline_stage="APPLIED", days_ago=10)
    recs = compute_follow_up_recommendations([(app, _job())], stale_after_days=7)
    assert len(recs) == 1
    assert recs[0].applied_days_ago == 10


def test_recent_application_never_surfaces():
    app = _application(pipeline_stage="APPLIED", days_ago=2)
    recs = compute_follow_up_recommendations([(app, _job())], stale_after_days=7)
    assert recs == []


def test_saved_and_shortlisted_never_surface_even_when_stale():
    saved = _application(pipeline_stage="SAVED", days_ago=30)
    shortlisted = _application(pipeline_stage="SHORTLISTED", days_ago=30)
    recs = compute_follow_up_recommendations(
        [(saved, _job()), (shortlisted, _job())], stale_after_days=7
    )
    assert recs == []


def test_terminal_stages_never_surface_even_when_stale():
    offer = _application(pipeline_stage="OFFER", days_ago=30)
    rejected = _application(pipeline_stage="REJECTED", days_ago=30)
    recs = compute_follow_up_recommendations(
        [(offer, _job()), (rejected, _job())], stale_after_days=7
    )
    assert recs == []


def test_interview_stage_gets_interview_specific_suggestion():
    app = _application(pipeline_stage="INTERVIEW", days_ago=14)
    recs = compute_follow_up_recommendations([(app, _job())], stale_after_days=7)
    assert "interview" in recs[0].suggested_action.lower()


def test_sorted_by_most_stale_first():
    fresher = _application(pipeline_stage="APPLIED", days_ago=8)
    staler = _application(pipeline_stage="APPLIED", days_ago=20)
    recs = compute_follow_up_recommendations(
        [(fresher, _job()), (staler, _job())], stale_after_days=7
    )
    assert recs[0].applied_days_ago == 20
    assert recs[1].applied_days_ago == 8


def test_empty_list_never_crashes():
    assert compute_follow_up_recommendations([]) == []

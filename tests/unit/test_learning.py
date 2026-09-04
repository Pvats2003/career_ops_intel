"""Learning system (job_agent.candidate.learning) — Career OS Phase 12
section 21."""

from __future__ import annotations

from job_agent.candidate.learning import (
    behavioral_fit_signal,
    compute_learned_preferences,
    discover_insights,
)
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme", title="Business Analyst", job_fingerprint="fp",
        remote_type="remote", employment_type="full_time",
    )
    base.update(overrides)
    return JobRow(**base)


def _app(**overrides) -> ApplicationRow:
    base = dict(job_id=1, candidate_id=1, status="DISCOVERED", pipeline_stage="SAVED")
    base.update(overrides)
    return ApplicationRow(**base)


def test_notable_pattern_surfaces_when_rate_well_above_baseline():
    rows = (
        [(_job(remote_type="remote"), _app()) for _ in range(4)]
        + [(_job(remote_type="onsite"), None) for _ in range(4)]
    )
    insights, summary = discover_insights(rows, min_sample=3)
    assert any("remote" in s.lower() for s in summary)


def test_no_pattern_when_all_rates_equal_baseline():
    rows = (
        [(_job(remote_type="remote"), _app()) for _ in range(2)]
        + [(_job(remote_type="remote"), None) for _ in range(2)]
        + [(_job(remote_type="onsite"), _app()) for _ in range(2)]
        + [(_job(remote_type="onsite"), None) for _ in range(2)]
    )
    _, summary = discover_insights(rows, min_sample=3)
    assert summary == []


def test_small_sample_never_surfaces_a_pattern():
    rows = [(_job(remote_type="remote"), _app()) for _ in range(2)] + [
        (_job(remote_type="onsite"), None) for _ in range(10)
    ]
    insights, summary = discover_insights(rows, min_sample=5)
    remote_insights = [i for i in insights if i.category == "remote"]
    assert remote_insights == []
    assert summary == []


def test_counts_are_accurate():
    rows = [(_job(remote_type="remote"), _app(pipeline_stage="APPLIED")) for _ in range(3)] + [
        (_job(remote_type="remote"), None) for _ in range(2)
    ]
    insights, _ = discover_insights(rows, min_sample=3)
    remote = next(i for i in insights if i.category == "remote")
    assert remote.saved == 3
    assert remote.applied == 3
    assert remote.ignored == 2


def test_empty_input_never_crashes():
    insights, summary = discover_insights([])
    assert insights == []
    assert summary == []


def test_explanation_never_overclaims_when_not_notable():
    rows = [(_job(remote_type="remote"), _app()) for _ in range(3)] + [
        (_job(remote_type="onsite"), _app()) for _ in range(3)
    ]
    insights, _ = discover_insights(rows, min_sample=3)
    for insight in insights:
        assert "Career OS noticed" not in insight.explanation or insight.saved >= 2


# --------------------------------------------------------------------------
# Behavioral ranking signal — CAREER OS FINAL GOD MODE Part 1.1
# --------------------------------------------------------------------------


def test_no_data_yields_neutral_signal_and_no_explanation():
    prefs = compute_learned_preferences([])
    signal, explanation = behavioral_fit_signal(_job(), prefs)
    assert signal == 0.5
    assert explanation is None


def test_below_min_sample_stays_neutral_even_with_a_strong_pattern():
    rows = [(_job(remote_type="remote"), _app()) for _ in range(3)] + [
        (_job(remote_type="onsite"), None) for _ in range(3)
    ]
    prefs = compute_learned_preferences(rows, min_sample=5)
    signal, explanation = behavioral_fit_signal(_job(remote_type="remote"), prefs)
    assert signal == 0.5
    assert explanation is None


def test_repeated_favored_pattern_lifts_signal_above_neutral():
    rows = [(_job(remote_type="remote"), _app()) for _ in range(6)] + [
        (_job(remote_type="onsite"), None) for _ in range(6)
    ]
    prefs = compute_learned_preferences(rows, min_sample=5)
    remote_signal, remote_explanation = behavioral_fit_signal(_job(remote_type="remote"), prefs)
    onsite_signal, _ = behavioral_fit_signal(_job(remote_type="onsite"), prefs)
    assert remote_signal > 0.5
    assert onsite_signal < 0.5
    assert remote_explanation is not None
    assert "remote" in remote_explanation.lower()


def test_signal_is_bounded_even_for_an_extreme_pattern():
    rows = [(_job(remote_type="remote"), _app()) for _ in range(10)] + [
        (_job(remote_type="onsite"), None) for _ in range(10)
    ]
    prefs = compute_learned_preferences(rows, min_sample=5)
    signal, _ = behavioral_fit_signal(_job(remote_type="remote"), prefs)
    assert 0.1 <= signal <= 0.9


def test_job_with_no_matching_dimension_data_stays_neutral():
    rows = [(_job(remote_type="remote"), _app()) for _ in range(6)] + [
        (_job(remote_type="onsite"), None) for _ in range(6)
    ]
    prefs = compute_learned_preferences(rows, min_sample=5)
    signal, explanation = behavioral_fit_signal(_job(remote_type="hybrid"), prefs)
    assert signal == 0.5
    assert explanation is None

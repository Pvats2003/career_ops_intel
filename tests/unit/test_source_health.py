"""Source Health — Career OS FINAL GOD MODE Part 6.19."""

from __future__ import annotations

from datetime import UTC, datetime

from job_agent.db.models import JobSource as JobSourceRow
from job_agent.jobs.source_health import suggest_action, summarize_source_health


def _source(**overrides) -> JobSourceRow:
    base = dict(name="greenhouse", kind="ats_api", enabled=True)
    base.update(overrides)
    return JobSourceRow(**base)


def test_never_checked_is_unknown():
    summary = summarize_source_health(_source(last_health_status=None))
    assert summary.status == "UNKNOWN"
    assert summary.last_error is None
    assert summary.suggested_action is None


def test_healthy_source_reports_no_error():
    now = datetime.now(UTC)
    summary = summarize_source_health(
        _source(last_health_status="healthy", last_health_check_at=now, last_success_at=now)
    )
    assert summary.status == "HEALTHY"
    assert summary.last_error is None
    assert summary.suggested_action is None
    assert summary.last_success_at == now


def test_unhealthy_source_reports_error_and_suggestion():
    summary = summarize_source_health(_source(last_health_status="unhealthy: Connection refused"))
    assert summary.status == "UNHEALTHY"
    assert summary.last_error == "Connection refused"
    assert summary.suggested_action is not None


def test_unhealthy_source_keeps_last_success_from_before_the_failure():
    """The whole point of last_success_at: a source failing NOW must still
    show when it last actually worked, not the failed check's timestamp."""
    earlier_success = datetime(2026, 9, 1, tzinfo=UTC)
    summary = summarize_source_health(
        _source(last_health_status="unhealthy: timeout", last_success_at=earlier_success)
    )
    assert summary.last_success_at == earlier_success


def test_suggest_action_for_missing_credentials():
    assert "credentials" in suggest_action("ADZUNA_APP_ID/ADZUNA_APP_KEY not set").lower()


def test_suggest_action_for_rate_limit():
    assert "rate" in suggest_action("429 Too Many Requests").lower()


def test_suggest_action_for_timeout():
    assert "slow or down" in suggest_action("Request timed out after 15s").lower()


def test_suggest_action_for_connection_error():
    assert "network" in suggest_action("Connection refused").lower()


def test_suggest_action_for_server_error():
    assert "server error" in suggest_action("HTTP 503 Service Unavailable").lower()


def test_suggest_action_falls_back_to_generic_for_unrecognized_error():
    assert suggest_action("Something bizarre happened") == (
        "Check the source's configuration in config/sources.yaml."
    )

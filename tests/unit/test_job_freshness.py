from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_agent.config.models import FreshnessSettings
from job_agent.jobs.freshness import classify_freshness
from job_agent.jobs.schema import FreshnessStatus

SETTINGS = FreshnessSettings(just_posted_hours=6, preferred_hours=24, recent_days=7)
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def test_none_posted_at_is_unknown():
    assert classify_freshness(None, now=NOW, settings=SETTINGS) == FreshnessStatus.UNKNOWN_POST_DATE


def test_just_posted():
    posted = NOW - timedelta(hours=1)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.JUST_POSTED


def test_new():
    posted = NOW - timedelta(hours=12)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.NEW


def test_recent():
    posted = NOW - timedelta(days=3)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.RECENT


def test_old():
    posted = NOW - timedelta(days=30)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.OLD


def test_naive_datetime_treated_as_utc():
    posted = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.JUST_POSTED


def test_future_posted_at_does_not_crash():
    posted = NOW + timedelta(hours=1)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.JUST_POSTED


def test_boundary_is_inclusive():
    posted = NOW - timedelta(hours=6)
    assert classify_freshness(posted, now=NOW, settings=SETTINGS) == FreshnessStatus.JUST_POSTED

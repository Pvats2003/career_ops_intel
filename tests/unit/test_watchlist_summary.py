"""Company Watchlist view — Career OS FINAL GOD MODE Part 5.16."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.jobs.watchlist_summary import summarize_watchlist


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme Corp",
        title="Business Analyst",
        job_fingerprint="fp",
        freshness_status="NEW",
        lifecycle_status="ACTIVE",
        discovered_at=datetime.now(UTC) - timedelta(days=1),
        posted_at=datetime.now(UTC) - timedelta(days=1),
    )
    base.update(overrides)
    return JobRow(**base)


def _match(overall_score: int) -> JobMatchRow:
    return JobMatchRow(
        job_id=1,
        candidate_id=1,
        overall_score=overall_score,
        decision="APPLY",
        reasoning="",
        missing_requirements=[],
        concerns=[],
        semantic_available=False,
    )


def _entry(kind: str, value: str) -> WatchlistEntryRow:
    return WatchlistEntryRow(candidate_id=1, kind=kind, value=value)


def test_no_matching_jobs_gives_zero_counts_and_none_scores():
    entries = [_entry("COMPANY", "Acme Corp")]
    summaries = summarize_watchlist(entries, [(_job(company_name="Other Co"), None)])
    assert summaries[0].matching_count == 0
    assert summaries[0].new_matching_count == 0
    assert summaries[0].highest_match_score is None
    assert summaries[0].latest_posted_at is None


def test_matching_active_job_counted():
    entries = [_entry("COMPANY", "Acme Corp")]
    summaries = summarize_watchlist(entries, [(_job(), None)])
    assert summaries[0].matching_count == 1


def test_inactive_job_never_counted():
    entries = [_entry("COMPANY", "Acme Corp")]
    summaries = summarize_watchlist(entries, [(_job(lifecycle_status="CLOSED"), None)])
    assert summaries[0].matching_count == 0


def test_recent_job_counts_as_new():
    entries = [_entry("COMPANY", "Acme Corp")]
    recent = _job(discovered_at=datetime.now(UTC) - timedelta(days=1))
    summaries = summarize_watchlist(entries, [(recent, None)])
    assert summaries[0].new_matching_count == 1


def test_old_job_not_counted_as_new():
    entries = [_entry("COMPANY", "Acme Corp")]
    old = _job(discovered_at=datetime.now(UTC) - timedelta(days=30))
    summaries = summarize_watchlist(entries, [(old, None)])
    assert summaries[0].new_matching_count == 0


def test_highest_match_score_among_matched_jobs():
    entries = [_entry("COMPANY", "Acme Corp")]
    pairs = [
        (_job(job_fingerprint="a"), _match(60)),
        (_job(job_fingerprint="b"), _match(88)),
        (_job(job_fingerprint="c"), None),
    ]
    summaries = summarize_watchlist(entries, pairs)
    assert summaries[0].highest_match_score == 88
    assert summaries[0].matching_count == 3


def test_latest_posted_at_is_the_max_across_matches():
    entries = [_entry("COMPANY", "Acme Corp")]
    older = datetime.now(UTC) - timedelta(days=5)
    newer = datetime.now(UTC) - timedelta(hours=2)
    pairs = [
        (_job(job_fingerprint="a", posted_at=older), None),
        (_job(job_fingerprint="b", posted_at=newer), None),
    ]
    summaries = summarize_watchlist(entries, pairs)
    assert summaries[0].latest_posted_at == newer


def test_each_entry_summarized_independently():
    entries = [_entry("COMPANY", "Acme Corp"), _entry("COMPANY", "Other Co")]
    summaries = summarize_watchlist(entries, [(_job(company_name="Acme Corp"), None)])
    by_value = {s.entry.value: s.matching_count for s in summaries}
    assert by_value["Acme Corp"] == 1
    assert by_value["Other Co"] == 0

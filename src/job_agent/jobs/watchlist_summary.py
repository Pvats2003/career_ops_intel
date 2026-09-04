"""Company Watchlist view — Career OS FINAL GOD MODE Part 5.16.

For each watched company/role/location, surfaces the three numbers that
actually answer "should I look at this watch entry today": how many
ACTIVE postings match it right now, how many of those are new in the
last window, the highest match score among them (when matched), and
the most recent posting date. Reuses `job_agent.jobs.watchlist.matches_entry`
— never a second, drifting definition of "matches this entry".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.jobs.watchlist import matches_entry

_DEFAULT_NEW_WINDOW_DAYS = 7


@dataclass(frozen=True)
class WatchlistEntrySummary:
    entry: WatchlistEntryRow
    matching_count: int
    new_matching_count: int
    highest_match_score: int | None
    latest_posted_at: datetime | None


def summarize_watchlist(
    entries: list[WatchlistEntryRow],
    jobs_with_matches: list[tuple[JobRow, JobMatch | None]],
    *,
    new_window_days: int = _DEFAULT_NEW_WINDOW_DAYS,
) -> list[WatchlistEntrySummary]:
    now = datetime.now(UTC)
    new_cutoff = now - timedelta(days=new_window_days)
    active_pairs = [(j, m) for j, m in jobs_with_matches if j.lifecycle_status == "ACTIVE"]

    summaries = []
    for entry in entries:
        matched = [(j, m) for j, m in active_pairs if matches_entry(j, entry)]

        discovered_at_values = [
            j.discovered_at if j.discovered_at.tzinfo else j.discovered_at.replace(tzinfo=UTC)
            for j, _ in matched
        ]
        new_matching_count = sum(1 for d in discovered_at_values if d > new_cutoff)

        scores = [m.overall_score for _, m in matched if m is not None]
        highest_match_score = int(max(scores)) if scores else None

        posted_dates = [j.posted_at or j.discovered_at for j, _ in matched]
        latest_posted_at = max(posted_dates) if posted_dates else None

        summaries.append(
            WatchlistEntrySummary(
                entry=entry,
                matching_count=len(matched),
                new_matching_count=new_matching_count,
                highest_match_score=highest_match_score,
                latest_posted_at=latest_posted_at,
            )
        )
    return summaries

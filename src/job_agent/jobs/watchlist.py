"""Watchlist matching — Career OS Phase 11 section 19.

Pure, deterministic matching against `WatchlistEntry` rows (the storage
model — see its docstring in `job_agent.db.models`): COMPANY does an
exact case-insensitive match against `Job.company_name` (a substring
match would false-positive "Meta" against "Metabase Inc"), ROLE does a
keyword-boundary match against `Job.title` (reusing `job_agent.matching.
text.contains_keyword`, the same word-boundary-aware matcher the rest of
the matching pipeline already uses), and LOCATION does a keyword-boundary
match against `Job.location` (falling back to `Job.remote_type` for a
"Remote" watch entry, since a fully-remote posting often has no location
string at all).
"""

from __future__ import annotations

from job_agent.db.models import Job as JobRow
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.matching.text import contains_keyword


def _matches_entry(job: JobRow, entry: WatchlistEntryRow) -> bool:
    if entry.kind == "COMPANY":
        return job.company_name.strip().casefold() == entry.value.strip().casefold()
    if entry.kind == "ROLE":
        return contains_keyword(job.title, entry.value)
    if entry.kind == "LOCATION":
        haystack = " ".join(filter(None, (job.location, job.remote_type)))
        return contains_keyword(haystack, entry.value)
    return False


def matching_entries(
    job: JobRow, entries: list[WatchlistEntryRow]
) -> tuple[WatchlistEntryRow, ...]:
    """Every watchlist entry this job matches — a job can match more than
    one (e.g. both a COMPANY entry and a ROLE entry)."""
    return tuple(entry for entry in entries if _matches_entry(job, entry))

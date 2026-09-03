"""Watchlist matching (job_agent.jobs.watchlist) — Career OS Phase 11
section 19."""

from __future__ import annotations

from job_agent.db.models import Job as JobRow
from job_agent.db.models import WatchlistEntry as WatchlistEntryRow
from job_agent.jobs.watchlist import matching_entries


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme Corp", title="Business Analyst", location="Remote - India",
        remote_type="remote", job_fingerprint="fp",
    )
    base.update(overrides)
    return JobRow(**base)


def _entry(kind: str, value: str) -> WatchlistEntryRow:
    return WatchlistEntryRow(candidate_id=1, kind=kind, value=value)


def test_company_entry_matches_exact_case_insensitive():
    job = _job(company_name="Acme Corp")
    assert matching_entries(job, [_entry("COMPANY", "acme corp")])


def test_company_entry_never_false_positives_on_substring():
    job = _job(company_name="Metabase Inc")
    assert not matching_entries(job, [_entry("COMPANY", "Meta")])


def test_role_entry_matches_keyword_in_title():
    job = _job(title="Senior Business Analyst")
    assert matching_entries(job, [_entry("ROLE", "Business Analyst")])


def test_role_entry_does_not_match_unrelated_title():
    job = _job(title="Software Engineer")
    assert not matching_entries(job, [_entry("ROLE", "Business Analyst")])


def test_location_entry_matches_location_field():
    job = _job(location="Bangalore, India")
    assert matching_entries(job, [_entry("LOCATION", "India")])


def test_location_entry_matches_remote_type_when_no_location():
    job = _job(location=None, remote_type="remote")
    assert matching_entries(job, [_entry("LOCATION", "remote")])


def test_job_can_match_multiple_entries():
    job = _job(company_name="Acme Corp", title="Business Analyst")
    entries = [_entry("COMPANY", "Acme Corp"), _entry("ROLE", "Business Analyst")]
    assert len(matching_entries(job, entries)) == 2


def test_empty_watchlist_never_matches():
    assert matching_entries(_job(), []) == ()

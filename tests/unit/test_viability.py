"""Application viability — Career OS FINAL GOD MODE Part 3.9. Every signal
is read straight off the job/match rows already in the DB; nothing here
makes a network call (see test_url_check.py for the one live check)."""

from __future__ import annotations

from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.jobs.viability import assess_application_viability


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme",
        title="Business Analyst",
        application_url="https://example.test/apply",
        job_fingerprint="fp",
        freshness_status="NEW",
        lifecycle_status="ACTIVE",
        visa_information="Sponsorship available for eligible candidates.",
    )
    base.update(overrides)
    return JobRow(**base)


def _match(**overrides) -> JobMatchRow:
    base = dict(
        job_id=1,
        candidate_id=1,
        overall_score=80,
        decision="APPLY",
        reasoning="Strong overlap.",
        missing_requirements=[],
        concerns=[],
        hard_stop_reasons=[],
        location_match=90.0,
        semantic_available=False,
    )
    base.update(overrides)
    return JobMatchRow(**base)


def test_fully_viable_job():
    result = assess_application_viability(_job(), _match())
    assert result.overall == "VIABLE"
    assert result.url_exists is True
    assert result.job_active is True
    assert result.qualifications_status == "MEETS"
    assert result.location_compatible is True
    assert result.visa_info_available is True


def test_no_application_url_is_blocked():
    result = assess_application_viability(_job(application_url=None), _match())
    assert result.overall == "BLOCKED"
    assert result.url_exists is False
    assert result.direct_application is False


def test_inactive_job_is_blocked():
    result = assess_application_viability(_job(lifecycle_status="CLOSED"), _match())
    assert result.overall == "BLOCKED"
    assert result.job_active is False


def test_hard_stop_reasons_are_caution_not_blocked():
    result = assess_application_viability(
        _job(), _match(hard_stop_reasons=["Requires a valid US work visa"])
    )
    assert result.overall == "CAUTION"
    assert result.qualifications_status == "GAPS"


def test_missing_requirements_without_hard_stop_are_caution():
    result = assess_application_viability(_job(), _match(missing_requirements=["SQL", "Tableau"]))
    assert result.overall == "CAUTION"
    assert result.qualifications_status == "GAPS"


def test_incompatible_location_is_caution():
    result = assess_application_viability(_job(), _match(location_match=10.0))
    assert result.overall == "CAUTION"
    assert result.location_compatible is False


def test_no_match_yet_is_unknown_qualifications_but_not_blocked():
    result = assess_application_viability(_job(), None)
    assert result.qualifications_status == "UNKNOWN"
    assert result.location_compatible is None
    # No match doesn't block viability on its own — URL + active job still stand.
    assert result.overall == "VIABLE"


def test_no_visa_information_is_flagged_but_not_blocking():
    result = assess_application_viability(_job(visa_information=None), _match())
    assert result.visa_info_available is False
    assert result.overall == "VIABLE"
    assert any("visa" in r.lower() for r in result.reasons)


def test_blocked_takes_priority_over_caution():
    result = assess_application_viability(
        _job(application_url=None), _match(hard_stop_reasons=["Needs sponsorship"])
    )
    assert result.overall == "BLOCKED"

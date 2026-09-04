"""Data confidence — Career OS FINAL GOD MODE Part 3.8. Confidence must be
computed only from fields actually present on the job row, never from the
match score, and must never claim High confidence when a load-bearing
field (salary, posting date, company link, application URL) is missing."""

from __future__ import annotations

from datetime import datetime

from job_agent.db.models import Job as JobRow
from job_agent.jobs.confidence import assess_data_confidence


def _job(**overrides) -> JobRow:
    base = dict(
        company_name="Acme",
        title="Business Analyst",
        application_url="https://example.test/apply",
        job_fingerprint="fp",
        freshness_status="NEW",
        lifecycle_status="ACTIVE",
        salary_min=80000,
        salary_max=110000,
        posted_at=datetime(2026, 9, 1),
        company_id=7,
    )
    base.update(overrides)
    return JobRow(**base)


def test_fully_specified_job_is_high_confidence():
    result = assess_data_confidence(_job())
    assert result.level == "High"
    assert result.reasons == []


def test_missing_salary_downgrades_to_medium():
    result = assess_data_confidence(_job(salary_min=None, salary_max=None))
    assert result.level == "Medium"
    assert any("salary" in r.lower() for r in result.reasons)


def test_unknown_posting_date_downgrades_to_medium():
    result = assess_data_confidence(_job(posted_at=None, freshness_status="UNKNOWN_POST_DATE"))
    assert result.level == "Medium"
    assert any("posting date" in r.lower() for r in result.reasons)


def test_posted_at_present_but_freshness_unknown_still_flags():
    result = assess_data_confidence(
        _job(posted_at=datetime(2026, 9, 1), freshness_status="UNKNOWN_POST_DATE")
    )
    assert result.level == "Medium"


def test_no_company_link_downgrades_to_medium():
    result = assess_data_confidence(_job(company_id=None, company_url=None))
    assert result.level == "Medium"
    assert any("company" in r.lower() for r in result.reasons)


def test_company_url_alone_is_sufficient():
    result = assess_data_confidence(_job(company_id=None, company_url="https://acme.example"))
    assert result.level == "High"


def test_no_application_url_downgrades_to_medium():
    result = assess_data_confidence(_job(application_url=None))
    assert result.level == "Medium"
    assert any("application url" in r.lower() for r in result.reasons)


def test_multiple_gaps_all_reported():
    result = assess_data_confidence(
        _job(salary_min=None, salary_max=None, application_url=None, company_id=None)
    )
    assert result.level == "Medium"
    assert len(result.reasons) >= 3

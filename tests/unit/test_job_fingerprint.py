from __future__ import annotations

from job_agent.jobs.fingerprint import canonicalize_url, compute_job_fingerprint, identity_key
from job_agent.jobs.schema import Job


def _job(**overrides) -> Job:
    defaults = dict(
        source="greenhouse",
        source_job_id="1",
        company="Acme Inc",
        title="Product Analyst",
        location="Remote - US",
        application_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_canonicalize_url_strips_query_and_trailing_slash():
    a = canonicalize_url("https://boards.greenhouse.io/acme/jobs/1?gh_src=abc&utm_source=x")
    b = canonicalize_url("https://boards.greenhouse.io/acme/jobs/1/")
    assert a == b == "https://boards.greenhouse.io/acme/jobs/1"


def test_fingerprint_is_deterministic():
    j1 = _job()
    j2 = _job()
    assert compute_job_fingerprint(j1) == compute_job_fingerprint(j2)


def test_fingerprint_ignores_tracking_params_and_case():
    j1 = _job(application_url="https://boards.greenhouse.io/acme/jobs/1?gh_src=abc")
    j2 = _job(
        company="ACME INC",
        title="PRODUCT ANALYST",
        application_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    assert compute_job_fingerprint(j1) == compute_job_fingerprint(j2)


def test_fingerprint_differs_for_different_jobs():
    j1 = _job(title="Product Analyst")
    j2 = _job(title="Business Analyst")
    assert compute_job_fingerprint(j1) != compute_job_fingerprint(j2)


def test_identity_key():
    assert identity_key("greenhouse", "111") == "greenhouse:111"
    assert identity_key("lever", "111") != identity_key("greenhouse", "111")

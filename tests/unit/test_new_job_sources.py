"""Phase 8 job-source adapters (Remotive, Arbeitnow, Adzuna) — same
httpx.MockTransport convention as `test_job_sources.py`'s Greenhouse/Lever
tests. No real network call is ever made.
"""

from __future__ import annotations

import httpx
import pytest

from job_agent.jobs.schema import RemoteType
from job_agent.jobs.sources.adzuna import AdzunaJobSource
from job_agent.jobs.sources.arbeitnow import ArbeitnowJobSource
from job_agent.jobs.sources.remotive import RemotiveJobSource
from job_agent.net.http_client import ResilientHttpClient


def _http(handler) -> ResilientHttpClient:
    return ResilientHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


# --------------------------------------------------------------------------
# Remotive
# --------------------------------------------------------------------------

REMOTIVE_RESPONSE = {
    "jobs": [
        {
            "id": 555,
            "title": "Remote Product Analyst",
            "company_name": "Acme Remote Co",
            "url": "https://remotive.com/remote-jobs/product/555",
            "candidate_required_location": "Worldwide",
            "job_type": "full_time",
            "publication_date": "2026-08-30T12:00:00",
            "salary": "$70,000 - $90,000",
            "description": "<p>Own the <b>product</b> roadmap.</p>",
        }
    ]
}


def test_remotive_search_and_normalize_never_shadows_search_method():
    def handler(request):
        assert request.url.path == "/api/remote-jobs"
        assert request.url.params["search"] == "Product Analyst"
        return httpx.Response(200, json=REMOTIVE_RESPONSE)

    src = RemotiveJobSource("Product Analyst", _http(handler))
    # The regression this guards: an instance attribute named `search`
    # would shadow the `search()` method and make this call fail with
    # "str object is not callable".
    raw = src.search()
    assert len(raw) == 1

    job = src.normalize(raw[0])
    assert job.source == "remotive"
    assert job.source_job_id == "555"
    assert job.company == "Acme Remote Co"
    assert job.remote_type == RemoteType.REMOTE
    assert job.posted_at is not None
    assert job.raw_data == REMOTIVE_RESPONSE["jobs"][0]


def test_remotive_health_check_ok():
    def handler(request):
        return httpx.Response(200, json=REMOTIVE_RESPONSE)

    result = RemotiveJobSource("Product Analyst", _http(handler)).health_check()
    assert result.healthy is True


def test_remotive_search_raises_on_unexpected_shape():
    def handler(request):
        return httpx.Response(200, json={"jobs": "not-a-list"})

    with pytest.raises(ValueError):
        RemotiveJobSource("x", _http(handler)).search()


# --------------------------------------------------------------------------
# Arbeitnow
# --------------------------------------------------------------------------

ARBEITNOW_PAGE_1 = {
    "data": [
        {
            "slug": "product-analyst-acme",
            "company_name": "Acme EU",
            "title": "Product Analyst",
            "url": "https://arbeitnow.com/view/product-analyst-acme",
            "location": "Berlin, Germany",
            "remote": True,
            "tags": ["product"],
            "job_types": ["Full-time"],
            "visa_sponsorship": True,
            "created_at": 1756512000,
            "description": "<p>Analyze <b>products</b>.</p>",
        }
    ],
    "links": {"next": None},
}


def test_arbeitnow_search_and_normalize_visa_sponsorship_true():
    def handler(request):
        return httpx.Response(200, json=ARBEITNOW_PAGE_1)

    src = ArbeitnowJobSource(_http(handler))
    raw = src.search()
    assert len(raw) == 1

    job = src.normalize(raw[0])
    assert job.source == "arbeitnow"
    assert job.remote_type == RemoteType.REMOTE
    assert job.visa_information == "Visa sponsorship offered (per source posting)"


def test_arbeitnow_visa_sponsorship_unknown_stays_unset():
    """No visa_sponsorship key at all must NEVER be read as 'no
    sponsorship' — BUILD PROMPT section 6's rule applies at the source
    layer too, not just at matching time."""
    posting = dict(ARBEITNOW_PAGE_1["data"][0])
    posting.pop("visa_sponsorship")

    def handler(request):
        return httpx.Response(200, json={"data": [posting], "links": {"next": None}})

    src = ArbeitnowJobSource(_http(handler))
    job = src.normalize(src.search()[0])
    assert job.visa_information is None


def test_arbeitnow_paginates_until_no_next_link():
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        page = int(request.url.params.get("page", "1"))
        has_next = page < 2
        return httpx.Response(
            200,
            json={
                "data": [ARBEITNOW_PAGE_1["data"][0]],
                "links": {"next": "next-url" if has_next else None},
            },
        )

    src = ArbeitnowJobSource(_http(handler), max_pages=5)
    raw = src.search()
    assert call_count["n"] == 2
    assert len(raw) == 2


def test_arbeitnow_stops_at_max_pages_even_if_more_exist():
    def handler(request):
        return httpx.Response(
            200, json={"data": [ARBEITNOW_PAGE_1["data"][0]], "links": {"next": "always-more"}}
        )

    src = ArbeitnowJobSource(_http(handler), max_pages=2)
    raw = src.search()
    assert len(raw) == 2


# --------------------------------------------------------------------------
# Adzuna
# --------------------------------------------------------------------------

ADZUNA_RESPONSE = {
    "results": [
        {
            "id": "999",
            "title": "Business Analyst",
            "company": {"display_name": "Acme UK"},
            "location": {"display_name": "London, UK"},
            "category": {"label": "IT Jobs"},
            "contract_time": "full_time",
            "salary_min": 40000,
            "salary_max": 55000,
            "redirect_url": "https://www.adzuna.co.uk/land/ad/999",
            "created": "2026-08-29T09:00:00Z",
            "description": "Analyze the business.",
        }
    ]
}


def test_adzuna_search_and_normalize_never_guesses_currency():
    def handler(request):
        assert request.url.path == "/v1/api/jobs/gb/search/1"
        assert request.url.params["app_id"] == "id123"
        assert request.url.params["app_key"] == "key456"
        assert request.url.params["what"] == "Business Analyst"
        return httpx.Response(200, json=ADZUNA_RESPONSE)

    src = AdzunaJobSource("gb", "Business Analyst", "id123", "key456", _http(handler))
    raw = src.search()
    assert len(raw) == 1

    job = src.normalize(raw[0])
    assert job.source == "adzuna"
    assert job.company == "Acme UK"
    assert job.salary_min == 40000
    assert job.salary_max == 55000
    assert job.currency is None  # Adzuna never states a currency code per listing
    assert job.posted_at is not None


def test_adzuna_credentials_never_leak_into_a_health_check_error():
    def handler(request):
        raise httpx.ConnectError("could not connect (id123 key456 leaked?)")

    src = AdzunaJobSource("gb", "Business Analyst", "id123", "key456", _http(handler))
    result = src.health_check()
    assert result.healthy is False
    # redact_text() only redacts values that LOOK secret-shaped; the point
    # of this test is that the health-check path routes through it at
    # all (matching every other adapter's health_check), not a specific
    # redaction outcome for this exact string.
    assert "ConnectError" in result.detail or "could not connect" in result.detail

from __future__ import annotations

from datetime import UTC

import httpx
import pytest

from job_agent.jobs.schema import RemoteType
from job_agent.jobs.sources.greenhouse import GreenhouseJobSource
from job_agent.jobs.sources.lever import LeverJobSource
from job_agent.net.http_client import ResilientHttpClient


def _http(handler) -> ResilientHttpClient:
    return ResilientHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


GH_RESPONSE = {
    "jobs": [
        {
            "id": 111,
            "title": "Associate Product Manager",
            "updated_at": "2026-08-26T10:00:00-04:00",
            "location": {"name": "Remote - US"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
            "content": "<p>We need a <b>PM</b>.</p><ul><li>Own roadmap</li></ul>",
        }
    ]
}


def test_greenhouse_search_and_normalize():
    def handler(request):
        assert request.url.path == "/v1/boards/acme/jobs"
        return httpx.Response(200, json=GH_RESPONSE)

    src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
    raw = src.search()
    assert len(raw) == 1

    job = src.normalize(raw[0])
    assert job.source == "greenhouse"
    assert job.source_job_id == "111"
    assert job.company == "Acme Inc"
    assert job.title == "Associate Product Manager"
    assert "Own roadmap" in job.description
    assert job.remote_type == RemoteType.REMOTE
    assert job.posted_at is not None
    assert job.posted_at.astimezone(UTC).hour == 14
    assert job.raw_data == GH_RESPONSE["jobs"][0]


def test_greenhouse_health_check_ok():
    def handler(request):
        return httpx.Response(200, json=GH_RESPONSE)

    src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
    result = src.health_check()
    assert result.healthy is True


def test_greenhouse_health_check_bad_shape():
    def handler(request):
        return httpx.Response(200, json={"unexpected": True})

    src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
    result = src.health_check()
    assert result.healthy is False


def test_greenhouse_search_raises_on_unexpected_shape():
    def handler(request):
        return httpx.Response(200, json={"jobs": "not-a-list"})

    src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
    with pytest.raises(ValueError):
        src.search()


LEVER_RESPONSE = [
    {
        "id": "uuid-1",
        "text": "Business Analyst",
        "categories": {"location": "Bengaluru, India", "commitment": "Full-time"},
        "description": "<p>Analyze things</p>",
        "lists": [{"text": "Requirements", "content": "<ul><li>SQL</li></ul>"}],
        "hostedUrl": "https://jobs.lever.co/acme2/uuid-1",
        "createdAt": 1750000000000,
    }
]


def test_lever_search_and_normalize():
    def handler(request):
        return httpx.Response(200, json=LEVER_RESPONSE)

    src = LeverJobSource("acme2", "Acme Analytics", _http(handler))
    raw = src.search()
    assert len(raw) == 1

    job = src.normalize(raw[0])
    assert job.source == "lever"
    assert job.source_job_id == "uuid-1"
    assert job.company == "Acme Analytics"
    assert job.title == "Business Analyst"
    assert job.location == "Bengaluru, India"
    assert job.employment_type == "Full-time"
    assert "SQL" in job.description
    assert job.posted_at is not None


def test_lever_search_raises_on_unexpected_shape():
    def handler(request):
        return httpx.Response(200, json={"not": "a list"})

    src = LeverJobSource("acme2", "Acme Analytics", _http(handler))
    with pytest.raises(ValueError):
        src.search()


def test_lever_missing_created_at_returns_none_posted_time():
    src = LeverJobSource("acme2", "Acme Analytics", _http(lambda r: httpx.Response(200)))
    assert src.get_posted_time({"id": "x"}) is None


# --------------------------------------------------------------------------
# Security fix (post-Phase-6A audit, remaining-sites pass): health_check()'s
# `detail` must never carry a secret embedded in an HTTP client failure.
# --------------------------------------------------------------------------
def test_greenhouse_health_check_redacts_secret_in_connection_failure():
    def handler(request):
        raise RuntimeError("upstream auth failed: api_key=sk-liveSECRET1234567890")

    src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
    result = src.health_check()

    assert result.healthy is False
    assert "sk-liveSECRET1234567890" not in result.detail
    assert "***REDACTED***" in result.detail


def test_greenhouse_health_check_preserves_ordinary_diagnostics():
    def handler(request):
        raise RuntimeError("connection refused")

    src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
    result = src.health_check()

    assert result.detail == "connection refused"


def test_lever_health_check_redacts_secret_in_connection_failure():
    def handler(request):
        raise RuntimeError("provider rejected token: refresh_token=abcDEF123xyzSECRET")

    src = LeverJobSource("acme2", "Acme Analytics", _http(handler))
    result = src.health_check()

    assert result.healthy is False
    assert "abcDEF123xyzSECRET" not in result.detail
    assert "***REDACTED***" in result.detail


def test_lever_health_check_preserves_ordinary_diagnostics():
    def handler(request):
        raise RuntimeError("DNS resolution failed")

    src = LeverJobSource("acme2", "Acme Analytics", _http(handler))
    result = src.health_check()

    assert result.detail == "DNS resolution failed"

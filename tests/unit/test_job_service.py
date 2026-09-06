from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from job_agent.config.loader import load_config
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.service import build_sources, run_scan, scan_source
from job_agent.jobs.source import HealthCheckResult, JobSource
from job_agent.jobs.sources.greenhouse import GreenhouseJobSource
from job_agent.jobs.sources.lever import LeverJobSource
from job_agent.net.http_client import ResilientHttpClient


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


def test_build_sources_greenhouse_and_lever_disabled_by_default(real_config):
    """Shipped config/sources.yaml has greenhouse/lever disabled (real board
    tokens require the candidate to say which companies to track — never
    fabricated) — no sources should be built for them, and no network call
    should ever be attempted for either. Real-world activation (2026-09-04)
    enabled the three keyless/free sources (remotive, arbeitnow, adzuna) by
    default, so this no longer asserts an empty list outright — it asserts
    specifically that greenhouse/lever contribute nothing, which is the
    property this test actually exists to guard."""
    http = ResilientHttpClient()
    try:
        sources = build_sources(real_config, http)
    finally:
        http.close()
    assert not any(isinstance(s, (GreenhouseJobSource, LeverJobSource)) for s in sources)


def test_build_sources_reads_enabled_boards(tmp_path, real_config):
    import shutil

    import yaml

    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    data = yaml.safe_load((cfg_dir / "sources.yaml").read_text())
    data["sources"]["greenhouse"]["enabled"] = True
    data["sources"]["greenhouse"]["boards"] = [{"token": "acme", "company_name": "Acme Inc"}]
    data["sources"]["lever"]["enabled"] = True
    data["sources"]["lever"]["boards"] = [{"token": "acme2", "company_name": "Acme Analytics"}]
    # Isolate this test to greenhouse/lever only — remotive/arbeitnow/adzuna
    # are enabled by default in the shipped config (real-world activation,
    # 2026-09-04) and would otherwise add unrelated sources to the result.
    data["sources"]["remotive"]["enabled"] = False
    data["sources"]["arbeitnow"]["enabled"] = False
    data["sources"]["adzuna"]["enabled"] = False
    (cfg_dir / "sources.yaml").write_text(yaml.dump(data))

    cfg = load_config(config_dir=cfg_dir)
    http = ResilientHttpClient()
    try:
        sources = build_sources(cfg, http)
    finally:
        http.close()

    assert len(sources) == 2
    assert isinstance(sources[0], GreenhouseJobSource)
    assert isinstance(sources[1], LeverJobSource)


GH_RESPONSE = {
    "jobs": [
        {
            "id": 111,
            "title": "Associate Product Manager",
            "updated_at": "2026-08-26T10:00:00-04:00",
            "location": {"name": "Remote - US"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
            "content": "<p>role</p>",
        }
    ]
}


def test_scan_source_persists_jobs(db_session, real_config):
    def handler(request):
        return httpx.Response(200, json=GH_RESPONSE)

    http = ResilientHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    src = GreenhouseJobSource("acme", "Acme Inc", http)

    result = scan_source(db_session, real_config, src)
    assert result.fetched == 1
    assert result.created == 1
    assert result.errors == []
    assert db_session.query(JobRow).count() == 1


def test_scan_source_records_error_without_crashing(db_session, real_config):
    def handler(request):
        return httpx.Response(200, json={"jobs": [{"id": 1}]})  # missing required 'title'

    http = ResilientHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    src = GreenhouseJobSource("acme", "Acme Inc", http)

    result = scan_source(db_session, real_config, src)
    assert result.fetched == 1
    assert result.created == 0
    assert len(result.errors) == 1


def test_run_scan_with_injected_sources(db_session, real_config):
    def handler(request):
        return httpx.Response(200, json=GH_RESPONSE)

    http = ResilientHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    src = GreenhouseJobSource("acme", "Acme Inc", http)

    results = run_scan(db_session, real_config, sources=[src])
    assert len(results) == 1
    assert results[0].created == 1


# --------------------------------------------------------------------------
# Security fix (post-Phase-6A audit, remaining-sites pass): ScanResult.errors
# is returned to `job-agent jobs scan`, which prints every entry verbatim —
# a source adapter's exception message must never reach that surface with a
# credential embedded in it.
# --------------------------------------------------------------------------
class _LeakySource(JobSource):
    """A minimal fake JobSource whose search()/fetch_job() can be made to
    raise an arbitrary exception on demand — isolates scan_source()'s own
    redaction wiring from ResilientHttpClient's retry/backoff behavior,
    which would otherwise make these tests slow and which Greenhouse/Lever
    already have their own mocked-HTTP tests for."""

    name = "leaky"

    def __init__(
        self, *, search_error: Exception | None = None, fetch_error: Exception | None = None
    ):
        self._search_error = search_error
        self._fetch_error = fetch_error

    def search(self):
        if self._search_error:
            raise self._search_error
        return [{"id": 1}]

    def fetch_job(self, raw):
        if self._fetch_error:
            raise self._fetch_error
        return raw

    def normalize(self, raw):
        raise AssertionError("normalize() should not be reached when fetch_job() already failed")

    def get_posted_time(self, raw):
        return None

    def health_check(self):
        return HealthCheckResult(healthy=True, detail="n/a", checked_at=datetime.now(UTC))


def test_scan_source_redacts_secret_in_top_level_search_failure(db_session, real_config):
    src = _LeakySource(
        search_error=RuntimeError("upstream auth failed: api_key=sk-liveSECRET1234567890")
    )
    result = scan_source(db_session, real_config, src)

    assert len(result.errors) == 1
    assert "sk-liveSECRET1234567890" not in result.errors[0]
    assert "***REDACTED***" in result.errors[0]


def test_scan_source_redacts_secret_in_per_posting_failure(db_session, real_config):
    src = _LeakySource(fetch_error=RuntimeError("upstream error: password=hunter2secretvalue"))
    result = scan_source(db_session, real_config, src)

    assert len(result.errors) == 1
    assert "hunter2secretvalue" not in result.errors[0]
    assert "***REDACTED***" in result.errors[0]
    assert "posting 1:" in result.errors[0]  # ordinary diagnostic context preserved


def test_scan_source_preserves_ordinary_error_diagnostics_when_nothing_sensitive_present(
    db_session, real_config
):
    """Confirms the fix does not blindly redact everything — an error with
    no secret-shaped content passes through unchanged."""
    src = _LeakySource(search_error=RuntimeError("connection timed out after 30s"))
    result = scan_source(db_session, real_config, src)

    assert result.errors == ["connection timed out after 30s"]


def test_run_scan_results_list_carries_redacted_errors_end_to_end(db_session, real_config):
    """The full run_scan() -> list[ScanResult] path (what the CLI actually
    consumes) still carries the redacted string, not the raw one."""
    src = _LeakySource(
        search_error=RuntimeError("provider rejected token: refresh_token=abcDEF123xyzSECRET")
    )
    results = run_scan(db_session, real_config, sources=[src])

    assert len(results) == 1
    assert "abcDEF123xyzSECRET" not in results[0].errors[0]

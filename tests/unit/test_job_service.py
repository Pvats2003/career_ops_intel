from __future__ import annotations

import httpx
import pytest

from job_agent.config.loader import load_config
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.service import build_sources, run_scan, scan_source
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


def test_build_sources_disabled_by_default(real_config):
    """Shipped config/sources.yaml has greenhouse/lever disabled -> no sources
    should be built, and no network call should ever be attempted."""
    http = ResilientHttpClient()
    try:
        sources = build_sources(real_config, http)
    finally:
        http.close()
    assert sources == []


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

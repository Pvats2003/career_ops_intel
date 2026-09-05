"""`job_agent.diagnostics.get_health_status()` — the same underlying check
`/api/health` exposes over HTTP. Verified directly (not just through the
HTTP layer) so the "genuinely up to date after a real Alembic run" and
"database unreachable" paths are each covered precisely, without needing
an HTTP round-trip for every case.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from job_agent.cli.main import _run_alembic_upgrade
from job_agent.config.loader import load_config
from job_agent.diagnostics import get_health_status


def _configure(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    db_path = tmp_path / "health_status_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(real_config.env.candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    return db_path


def test_migrations_current_true_after_a_real_alembic_upgrade(tmp_path, monkeypatch, real_config):
    _configure(tmp_path, monkeypatch, real_config)
    cfg = load_config()
    _run_alembic_upgrade(cfg.env.database_url)

    status = get_health_status(cfg)
    assert status["database"]["connected"] is True
    assert status["database"]["migrations_current"] is True


def test_database_unreachable_is_reported_not_crashed(tmp_path, monkeypatch, real_config):
    _configure(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/void")
    cfg = load_config()

    status = get_health_status(cfg)
    assert status["database"]["connected"] is False
    assert status["database"]["migrations_current"] is False


def test_health_status_never_contains_the_database_url_or_credentials(
    tmp_path, monkeypatch, real_config
):
    _configure(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret-value")
    cfg = load_config()

    status = get_health_status(cfg)
    serialized = str(status)
    assert "sk-ant-super-secret-value" not in serialized
    assert str(tmp_path) not in serialized
    assert status["llm"]["configured"] is True


def test_remotive_arbeitnow_report_enabled_by_default(tmp_path, monkeypatch, real_config):
    _configure(tmp_path, monkeypatch, real_config)
    cfg = load_config()

    status = get_health_status(cfg)
    assert status["job_sources"]["remotive"] == "enabled"
    assert status["job_sources"]["arbeitnow"] == "enabled"
    assert status["job_sources"]["adzuna"] == "enabled_no_credentials"
    assert status["job_sources"]["greenhouse"] == "disabled"
    assert status["job_sources"]["lever"] == "disabled"

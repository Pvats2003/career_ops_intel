"""`job-agent doctor` — local-activation-package diagnostics.

Verifies the doctor never fabricates network reachability, correctly
surfaces NOT CONFIGURED preference fields, and correctly distinguishes
keyless sources (Remotive/Arbeitnow) from credential-gated ones (Adzuna)
and placeholder-gated ones (Greenhouse/Lever).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from typer.testing import CliRunner

from job_agent.cli.main import app
from job_agent.diagnostics import run_doctor

runner = CliRunner()


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "profile.md").write_text(
        "## Identity\nname: Test Candidate\ncurrent_location: Remote\n\n"
        "## Contact\nemail: test@example.invalid\nphone: +1-555-0100\n"
        "linkedin: https://linkedin.com/in/test\n"
    )
    for filename in (
        "experience.md", "projects.md", "skills.md", "education.md", "achievements.md",
    ):
        (candidate_dir / filename).write_text("")
    (candidate_dir / "answers").mkdir()
    db_path = tmp_path / "doctor_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "250")
    return cfg_dir


def test_network_is_never_reported_as_pass(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    report = run_doctor()
    network = next(c for c in report.checks if c.name.startswith("Network"))
    assert network.status == "UNKNOWN"


def test_missing_preferences_are_reported_as_not_configured(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    report = run_doctor()
    prefs = next(c for c in report.checks if c.name == "Candidate preferences")
    assert prefs.status == "WARN"
    assert "NOT CONFIGURED" in prefs.detail


def test_fully_filled_preferences_pass(tmp_path, monkeypatch, real_config):
    cfg_dir = _configure_env(tmp_path, monkeypatch, real_config)
    prefs_path = cfg_dir / "preferences.yaml"
    data = yaml.safe_load(prefs_path.read_text())
    data["work_preferences"]["remote"] = "remote"
    data["work_preferences"]["willing_to_relocate"] = "true"
    data["work_preferences"]["notice_period"] = "immediate"
    data["location_preferences"]["open_to_countries"] = "worldwide"
    data["salary_preferences"] = {
        "currency": "USD", "minimum_annual": "50000", "target_annual": "60000",
        "negotiable": "true",
    }
    data["visa_information"] = {
        "nationality": "Testland", "requires_sponsorship_us": "true",
        "requires_sponsorship_uk": "true", "requires_sponsorship_eu": "true",
        "requires_sponsorship_other": "true", "currently_authorized_countries": [],
    }
    data["availability"]["earliest_start_date"] = "2026-01-01"
    prefs_path.write_text(yaml.safe_dump(data))

    report = run_doctor()
    prefs = next(c for c in report.checks if c.name == "Candidate preferences")
    assert prefs.status == "PASS"


def test_adzuna_enabled_without_credentials_warns_not_pass(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    report = run_doctor()
    adzuna = next(c for c in report.checks if c.name == "Adzuna")
    assert adzuna.status == "WARN"
    assert "ADZUNA_APP_ID" in adzuna.detail


def test_adzuna_enabled_with_credentials_passes(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    report = run_doctor()
    adzuna = next(c for c in report.checks if c.name == "Adzuna")
    assert adzuna.status == "PASS"


def test_greenhouse_disabled_by_default_warns(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    report = run_doctor()
    greenhouse = next(c for c in report.checks if c.name == "Greenhouse")
    assert greenhouse.status == "WARN"


def test_greenhouse_enabled_with_placeholder_token_is_an_error(tmp_path, monkeypatch, real_config):
    cfg_dir = _configure_env(tmp_path, monkeypatch, real_config)
    sources_path = cfg_dir / "sources.yaml"
    data = yaml.safe_load(sources_path.read_text())
    data["sources"]["greenhouse"]["enabled"] = True
    sources_path.write_text(yaml.safe_dump(data))

    report = run_doctor()
    greenhouse = next(c for c in report.checks if c.name == "Greenhouse")
    assert greenhouse.status == "ERROR"
    assert "placeholder" in greenhouse.detail


def test_doctor_cli_exits_nonzero_on_error(tmp_path, monkeypatch, real_config):
    cfg_dir = _configure_env(tmp_path, monkeypatch, real_config)
    sources_path = cfg_dir / "sources.yaml"
    data = yaml.safe_load(sources_path.read_text())
    data["sources"]["greenhouse"]["enabled"] = True
    sources_path.write_text(yaml.safe_dump(data))

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1, result.output
    assert "ERROR" in result.output


def test_doctor_cli_exits_zero_with_only_warnings(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "CAREER OS DOCTOR" in result.output


def test_anthropic_unset_warns_not_error(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    report = run_doctor()
    anthropic = next(c for c in report.checks if c.name == "Anthropic (LLM)")
    assert anthropic.status == "WARN"


def test_anthropic_set_passes(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    report = run_doctor()
    anthropic = next(c for c in report.checks if c.name == "Anthropic (LLM)")
    assert anthropic.status == "PASS"

"""Phase 6D Stage 2 — CLI integration tests for `applications browser-preview`
(`typer.testing.CliRunner`, in-process, against a temporary sqlite database
and a temporary copy of the real config directory — the same convention
`test_cli_applications_phase6c.py` already established).

Every test that reaches the live-network branch (`--confirm` passed and
the `--url` matches) points at a LOCAL synthetic fixture served on
127.0.0.1 by the shared `site_server` fixture — never a real site.

The CLI command owns its own Playwright lifecycle end to end (launch,
use, close) — the right design for a real, standalone CLI invocation.
That conflicts with this test session's shared, session-scoped `browser`
fixture (tests/conftest.py): Playwright's sync API allows only one
active `sync_playwright()` context per thread, and pytest runs a whole
session in one thread. `patched_sync_playwright` below redirects the
CLI's own `sync_playwright()`/`chromium.launch()` calls to reuse that
already-open shared browser instead of opening a second one, and makes
the CLI's own `browser.close()` a no-op so it never tears down the
shared browser out from under every other test still using it. This
changes nothing about the CLI command's real, production behavior —
only how this test suite avoids a same-process resource conflict that
only exists because many tests share one process.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import playwright.sync_api as playwright_sync_api
import pytest
from typer.testing import CliRunner

from job_agent.cli.main import app
from job_agent.db.models import Application, Company, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db

pytest.importorskip("playwright.sync_api")

CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)

runner = CliRunner()


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    db_path = tmp_path / "cli_browser_preview_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "250")
    return db_path


def _seed_application(
    db_path: Path, real_profile, *, application_url: str, fingerprint: str
) -> tuple[int, int]:
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        candidate_id = save_candidate_profile(session, real_profile)

        company = Company(name=f"Acme-{fingerprint}")
        session.add(company)
        session.flush()
        source = JobSource(name=f"cli-browser-preview-{fingerprint}", kind="ats_api", enabled=True)
        session.add(source)
        session.flush()
        job = JobRow(
            source_id=source.id, source_job_id=fingerprint, company_id=company.id,
            company_name="Drivetrain", title="Business Analyst - Customer Platform",
            application_url=application_url, job_fingerprint=fingerprint,
        )
        session.add(job)
        session.flush()

        application = Application(job_id=job.id, candidate_id=candidate_id, status="MATCHED")
        session.add(application)
        session.commit()
        return application.id, job.id


class _NonClosingBrowserProxy:
    """Delegates everything to the wrapped Browser except close(), which
    is a no-op. The CLI command calls browser.close() itself when it's
    done — entirely correct for a real, standalone invocation — but here
    the "browser" it's holding is this test session's shared,
    session-scoped fixture; closing it for real would break every other
    test still relying on it for the rest of the session."""

    def __init__(self, real_browser):
        self._real_browser = real_browser

    def __getattr__(self, name):
        return getattr(self._real_browser, name)

    def close(self) -> None:
        pass


@pytest.fixture()
def patched_sync_playwright(monkeypatch, browser):
    """Redirects the CLI command's own `sync_playwright()`/
    `chromium.launch()` calls to reuse the already-open, shared `browser`
    fixture instead of opening a second Playwright context — see module
    docstring for why. Returns the list of "launch" calls so a test can
    assert whether the CLI ever reached that point at all."""
    calls: list[dict] = []

    class _FakeChromium:
        @staticmethod
        def launch(**kwargs):
            calls.append(dict(kwargs))
            return _NonClosingBrowserProxy(browser)

    class _FakePlaywright:
        chromium = _FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(playwright_sync_api, "sync_playwright", lambda: _FakePlaywright())
    return calls


def _drivetrain_native_url(site_server: str) -> str:
    return f"{site_server}/drivetrain_business_analyst_native.html"


# ==========================================================================
# Safe-by-default: no --confirm makes no network call.
# ==========================================================================
def test_without_confirm_makes_no_network_call(
    tmp_path, monkeypatch, real_config, patched_sync_playwright
):
    _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(
        app, ["applications", "browser-preview", "999", "--url", "https://example.test/apply"]
    )
    assert result.exit_code == 0
    assert "No action taken" in result.output
    assert patched_sync_playwright == []  # never launched


def test_unknown_application_id_errors_before_any_network_call(
    tmp_path, monkeypatch, real_config, patched_sync_playwright
):
    _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(
        app,
        [
            "applications", "browser-preview", "999999",
            "--url", "https://example.test/apply", "--confirm",
        ],
    )
    assert result.exit_code == 1
    assert "No application with id" in result.output
    assert patched_sync_playwright == []


def test_url_mismatch_rejected_before_any_network_call(
    tmp_path, monkeypatch, real_config, real_profile, patched_sync_playwright
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    application_id, _ = _seed_application(
        db_path, real_profile,
        application_url="https://real.example.test/apply", fingerprint="url-mismatch",
    )
    result = runner.invoke(
        app,
        [
            "applications", "browser-preview", str(application_id),
            "--url", "https://a-different-url.example.test/apply", "--confirm",
        ],
    )
    assert result.exit_code == 1
    assert "does not match this job's own application_url" in result.output
    assert patched_sync_playwright == []


# ==========================================================================
# Live path — always against a local synthetic fixture only.
# ==========================================================================
def test_happy_path_renders_snapshot_all_fields_unresolved_with_no_llm_configured(
    tmp_path, monkeypatch, real_config, real_profile, patched_sync_playwright, site_server
):
    """No ANTHROPIC_API_KEY is configured (autouse fixture strips it, and
    this test never sets one) and no answer-bank entry exists for any of
    these contact-identity fields — matching the empirical finding from
    the Drivetrain compatibility check, EVERY field must end up
    unresolved, never fabricated. This is the correct, safe outcome, not
    a test weakness."""
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _drivetrain_native_url(site_server)
    application_id, _ = _seed_application(
        db_path, real_profile, application_url=url, fingerprint="happy-path",
    )

    result = runner.invoke(
        app, ["applications", "browser-preview", str(application_id), "--url", url, "--confirm"]
    )

    assert result.exit_code == 0, result.output
    assert len(patched_sync_playwright) == 1
    assert "Drivetrain" in result.output
    assert "Business Analyst - Customer Platform" in result.output
    assert "Needs your input" in result.output
    for field_id in (
        "full_name", "email", "phone", "current_location",
        "current_company", "linkedin_url",
    ):
        assert field_id in result.output
    assert "structurally unavailable" in result.output


def test_captcha_scenario_stops_before_filling_anything(
    tmp_path, monkeypatch, real_config, real_profile, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = f"{site_server}/index.html?scenario=captcha"
    application_id, _ = _seed_application(
        db_path, real_profile, application_url=url, fingerprint="captcha-scenario",
    )

    result = runner.invoke(
        app, ["applications", "browser-preview", str(application_id), "--url", url, "--confirm"]
    )

    assert result.exit_code == 0, result.output
    assert "Human review required" in result.output
    assert "nothing was filled" in result.output
    assert "Needs your input" not in result.output  # never reached the snapshot stage

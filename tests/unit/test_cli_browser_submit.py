"""Final real-execution checkpoint — CLI integration tests for
`applications browser-submit`: the ONLY command that can click a real
submit control, gated by its OWN, SEPARATE `browser-approve` run (never
reusing the approval `browser-fill` already consumed).

Local synthetic end-to-end (Step 12): target-add -> browser-approve
(the submit-specific one) -> browser-submit --confirm-submit ->
COMPLETED, entirely against `submission_target.html` ->
`submission_success.html` served on 127.0.0.1. No real network, no real
candidate PII, no credentials.

Same conventions as `test_cli_browser_approve_fill.py`: `typer.testing.
CliRunner`, in-process, temporary sqlite DB + config copy, `CANDIDATE_DIR`
always points at a synthetic candidate directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import playwright.sync_api as playwright_sync_api
import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.cli.main import app
from job_agent.db.models import (
    Application,
    ApplicationApproval,
    ApplicationEvent,
    Company,
    JobSource,
)
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

SYNTHETIC_VALUES = {
    "full_name": "Test Candidate",
    "email": "test.candidate@example.invalid",
    "phone": "+1-555-0100",
    "current_location": "Test City, Test Country",
    "linkedin_url": "https://linkedin.com/in/testcandidate",
    "current_company": "Synthetic Employer Inc.",
}


def _fact(value: str) -> Fact[str]:
    return Fact[str](value=value, source="test_synthetic_profile", confidence=1.0, verified=True)


def _synthetic_identity_profile() -> CandidateProfile:
    unknown_pref = Fact.unknown(source="test_synthetic_profile")
    return CandidateProfile(
        identity_name=_fact(SYNTHETIC_VALUES["full_name"]),
        identity_current_location=_fact(SYNTHETIC_VALUES["current_location"]),
        contact_email=_fact(SYNTHETIC_VALUES["email"]),
        contact_phone=_fact(SYNTHETIC_VALUES["phone"]),
        contact_linkedin=_fact(SYNTHETIC_VALUES["linkedin_url"]),
        target_roles=TargetRoles(),
        work_preferences=WorkPreferences(
            remote=unknown_pref, willing_to_relocate=unknown_pref, notice_period=unknown_pref
        ),
        location_preferences=LocationPreferences(
            current_location=_fact(SYNTHETIC_VALUES["current_location"]),
            open_to_countries=unknown_pref,
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown_pref, minimum_annual=unknown_pref,
            target_annual=unknown_pref, negotiable=unknown_pref,
        ),
        visa_information=VisaInformation(
            nationality=unknown_pref, requires_sponsorship_us=unknown_pref,
            requires_sponsorship_uk=unknown_pref, requires_sponsorship_eu=unknown_pref,
            requires_sponsorship_other=unknown_pref,
        ),
    )


def _make_synthetic_candidate_dir(candidate_dir: Path) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "profile.md").write_text(
        "## Identity\n"
        f"name: {SYNTHETIC_VALUES['full_name']}\n"
        f"current_location: {SYNTHETIC_VALUES['current_location']}\n"
        "\n"
        "## Contact\n"
        f"email: {SYNTHETIC_VALUES['email']}\n"
        f"phone: {SYNTHETIC_VALUES['phone']}\n"
        f"linkedin: {SYNTHETIC_VALUES['linkedin_url']}\n"
    )
    for filename in (
        "experience.md", "projects.md", "skills.md", "education.md", "achievements.md",
    ):
        (candidate_dir / filename).write_text("")
    (candidate_dir / "answers").mkdir(exist_ok=True)

    import docx

    document = docx.Document()
    document.add_paragraph("Synthetic test resume for browser-submit tests. No real content.")
    document.save(str(candidate_dir / "resume_master.docx"))
    return candidate_dir


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    candidate_dir = _make_synthetic_candidate_dir(tmp_path / "candidate")
    db_path = tmp_path / "cli_browser_submit_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "250")
    return db_path


def _seed_application(
    db_path: Path, profile: CandidateProfile, *, application_url: str, fingerprint: str
) -> tuple[int, int]:
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        candidate_id = save_candidate_profile(session, profile)
        company = Company(name=f"Acme-{fingerprint}")
        session.add(company)
        session.flush()
        source = JobSource(
            name=f"cli-browser-submit-{fingerprint}", kind="ats_api", enabled=True
        )
        session.add(source)
        session.flush()
        job = JobRow(
            source_id=source.id, source_job_id=fingerprint, company_id=company.id,
            company_name="Synthetic Co", title="Business Analyst",
            application_url=application_url, job_fingerprint=fingerprint,
        )
        session.add(job)
        session.flush()
        application = Application(job_id=job.id, candidate_id=candidate_id, status="MATCHED")
        session.add(application)
        session.commit()
        return application.id, job.id


class _NonClosingBrowserProxy:
    def __init__(self, real_browser):
        self._real_browser = real_browser

    def __getattr__(self, name):
        return getattr(self._real_browser, name)

    def close(self) -> None:
        pass


@pytest.fixture()
def patched_sync_playwright(monkeypatch, browser):
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


def _url(site_server: str) -> str:
    return f"{site_server}/submission_target.html"


def _answer_args() -> list[str]:
    return ["--answer", f"Current company={SYNTHETIC_VALUES['current_company']}"]


def _approve_args(application_id: int, url: str) -> list[str]:
    return [
        "applications", "browser-approve", str(application_id), "--url", url,
        "--confirm", "--yes", *_answer_args(),
    ]


def _submit_preview_args(application_id: int, url: str) -> list[str]:
    return [
        "applications", "browser-submit", str(application_id), "--url", url,
        "--confirm", *_answer_args(),
    ]


def _submit_args(application_id: int, url: str) -> list[str]:
    return [
        "applications", "browser-submit", str(application_id), "--url", url,
        "--confirm", "--confirm-submit", *_answer_args(),
    ]


# ==========================================================================
# Safe-by-default.
# ==========================================================================
def test_without_confirm_makes_no_network_call(
    tmp_path, monkeypatch, real_config, patched_sync_playwright
):
    _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(
        app, ["applications", "browser-submit", "999", "--url", "https://example.test/apply"]
    )
    assert result.exit_code == 0
    assert "No action taken" in result.output
    assert patched_sync_playwright == []


def test_confirm_alone_never_clicks(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    """--confirm without --confirm-submit previews everything but clicks
    nothing -- the command must NOT interpret --confirm as submission
    authorization."""
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="confirm-alone",
    )
    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0

    result = runner.invoke(app, _submit_preview_args(application_id, url))
    assert result.exit_code == 0, result.output
    assert "APPLICATION SUBMISSION" in result.output
    assert "Pass --confirm-submit" in result.output
    assert "COMPLETED" not in result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        application = session.get(Application, application_id)
        assert application.submitted_at is None
        approvals = session.execute(
            select(ApplicationApproval).where(
                ApplicationApproval.application_id == application_id
            )
        ).scalars().all()
        assert len(approvals) == 1
        assert approvals[0].consumed_at is None  # never consumed -- nothing was clicked


# ==========================================================================
# Step 12: full local synthetic E2E.
# ==========================================================================
def test_full_end_to_end_approve_then_submit_completes(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="full-e2e",
    )

    approve_result = runner.invoke(app, _approve_args(application_id, url))
    assert approve_result.exit_code == 0, approve_result.output

    submit_result = runner.invoke(app, _submit_args(application_id, url))
    assert submit_result.exit_code == 0, submit_result.output
    assert "COMPLETED" in submit_result.output
    assert "submission_success.html" in submit_result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        application = session.get(Application, application_id)
        assert application.submitted_at is not None
        assert application.confirmation_url is not None
        assert "submission_success.html" in application.confirmation_url

        events = session.execute(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == application_id,
                ApplicationEvent.event_type == "BROWSER_SUBMIT_COMPLETED",
            )
        ).scalars().all()
        assert len(events) == 1

        approvals = session.execute(
            select(ApplicationApproval).where(
                ApplicationApproval.application_id == application_id
            )
        ).scalars().all()
        assert len(approvals) == 1
        assert approvals[0].consumed_at is not None


def test_duplicate_submission_is_refused(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    """Prove the submit click occurs exactly once: a second browser-submit
    invocation after a completed submission must refuse, even with a
    brand new approval."""
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="duplicate",
    )

    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0
    first = runner.invoke(app, _submit_args(application_id, url))
    assert first.exit_code == 0, first.output
    assert "COMPLETED" in first.output

    # Even with a FRESH approval, a second submit must be refused because
    # this application already has a recorded submission.
    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0
    second = runner.invoke(app, _submit_args(application_id, url))
    assert second.exit_code == 1, second.output
    assert "already has a recorded submission" in second.output
    assert "COMPLETED" not in second.output


def test_submit_without_any_approval_refuses(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="no-approval",
    )
    result = runner.invoke(app, _submit_args(application_id, url))
    assert result.exit_code == 1, result.output
    assert "No valid approval matches" in result.output
    assert "COMPLETED" not in result.output


def test_fill_approval_cannot_authorize_submit(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    """The approval browser-fill consumes is NOT reusable for
    browser-submit -- submission requires its OWN, separate approval."""
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="fill-not-submit",
    )
    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0
    fill_result = runner.invoke(
        app,
        [
            "applications", "browser-fill", str(application_id), "--url", url,
            "--confirm", *_answer_args(),
        ],
    )
    assert fill_result.exit_code == 0, fill_result.output

    submit_result = runner.invoke(app, _submit_args(application_id, url))
    assert submit_result.exit_code == 1, submit_result.output
    assert "No valid approval matches" in submit_result.output


def test_drifted_answer_at_submit_time_refuses(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="drift",
    )
    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0

    drifted = runner.invoke(
        app,
        [
            "applications", "browser-submit", str(application_id), "--url", url,
            "--confirm", "--confirm-submit",
            "--answer", "Current company=A Totally Different Employer",
        ],
    )
    assert drifted.exit_code == 1, drifted.output
    assert "No valid approval matches" in drifted.output
    assert "A Totally Different Employer" not in drifted.output


def test_captcha_at_submit_time_refuses_before_clicking(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    approve_url = _url(site_server)
    application_id, job_id = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=approve_url,
        fingerprint="captcha-at-submit",
    )
    assert runner.invoke(app, _approve_args(application_id, approve_url)).exit_code == 0

    captcha_url = f"{site_server}/index.html?scenario=captcha"
    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        job = session.get(JobRow, job_id)
        job.application_url = captcha_url
        session.commit()

    result = runner.invoke(
        app,
        [
            "applications", "browser-submit", str(application_id), "--url", captcha_url,
            "--confirm", "--confirm-submit",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Human review required" in result.output
    assert "COMPLETED" not in result.output


def test_unresolved_question_refuses_submission(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="unresolved",
    )
    result = runner.invoke(
        app,
        ["applications", "browser-submit", str(application_id), "--url", url, "--confirm"],
    )
    assert result.exit_code == 1, result.output
    assert "still has question(s) requiring human input" in result.output


def test_no_password_or_credential_in_events_or_output(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="event-audit",
    )
    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0
    result = runner.invoke(app, _submit_args(application_id, url))
    assert result.exit_code == 0, result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        events = session.execute(
            select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
        ).scalars().all()
        for event in events:
            details_text = str(event.details)
            for forbidden in ("password", "credential", "secret", "token", "api_key"):
                assert forbidden not in details_text.lower()


def test_resume_never_auto_attached_at_submit(
    tmp_path, monkeypatch, real_config, patched_sync_playwright, site_server
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    url = _url(site_server)
    application_id, _ = _seed_application(
        db_path, _synthetic_identity_profile(), application_url=url, fingerprint="no-resume",
    )
    assert runner.invoke(app, _approve_args(application_id, url)).exit_code == 0
    result = runner.invoke(app, _submit_args(application_id, url))
    assert result.exit_code == 0, result.output
    assert "Resume:" in result.output
    assert "Not attached" in result.output


def test_browser_submit_never_calls_verify_or_allowlist_code():
    source = Path("src/job_agent/cli/main.py").read_text()
    start = source.index('@applications_app.command("browser-submit")')
    end = source.index('@applications_app.command("run")')
    body = source[start:end]
    forbidden = (
        "create_allowlist_entry(", "revoke_allowlist_entry(",
        "provider.submit(", "provider.verify(",
        "submit_application(", "verify_application(",
        "EnvCredentialStore", "SubmissionHttpClient",
    )
    for term in forbidden:
        assert term not in body

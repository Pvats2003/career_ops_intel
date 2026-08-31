"""Real-target-readiness checkpoint — `applications target-add`:
registers exactly ONE explicit job/application target from a URL,
company, and title, with NO network call and NO discovery of any other
job. `typer.testing.CliRunner`, in-process, against a temporary sqlite
database and a temporary copy of the real config directory (the same
convention `test_cli_browser_preview.py` already established).

PRIVACY: `target-add` calls `parse_candidate_profile(cfg)`, which reads
`cfg.env.candidate_dir` — defaults to the repository's REAL `candidate/`
directory unless `CANDIDATE_DIR` is overridden. `_configure_env()` below
points it at a minimal, entirely synthetic directory for every test in
this file, exactly like `test_cli_browser_preview.py` does, so nothing
printed by these tests (including on assertion failure) can ever be real
candidate data.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from job_agent.cli.main import app
from job_agent.db.models import Application, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory

runner = CliRunner()

SYNTHETIC_VALUES = {
    "full_name": "Test Candidate",
    "email": "test.candidate@example.invalid",
    "phone": "+1-555-0100",
    "current_location": "Test City, Test Country",
    "linkedin_url": "https://linkedin.com/in/testcandidate",
}


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
    document.add_paragraph("Synthetic test resume for target-add tests. No real content.")
    document.save(str(candidate_dir / "resume_master.docx"))
    return candidate_dir


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    candidate_dir = _make_synthetic_candidate_dir(tmp_path / "candidate")
    db_path = tmp_path / "cli_target_add_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "250")
    return db_path


TARGET_URL = "https://jobs.example.test/synthetic-target/apply"


def test_target_can_be_registered_from_an_explicit_url(tmp_path, monkeypatch, real_config):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(
        app,
        [
            "applications", "target-add",
            "--url", TARGET_URL, "--company", "Acme Corp", "--title", "Synthetic Role",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Target registered" in result.output
    assert "browser-preview" in result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        job = session.execute(
            select(JobRow).where(JobRow.application_url == TARGET_URL)
        ).scalar_one()
        assert job.company_name == "Acme Corp"
        assert job.title == "Synthetic Role"
        application = session.execute(
            select(Application).where(Application.job_id == job.id)
        ).scalar_one()
        assert application is not None


def test_target_metadata_is_preserved_exactly(tmp_path, monkeypatch, real_config):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(
        app,
        [
            "applications", "target-add",
            "--url", TARGET_URL, "--company", "Drivetrain",
            "--title", "Business Analyst - Customer Platform", "--location", "India, Remote",
        ],
    )
    assert result.exit_code == 0, result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        job = session.execute(
            select(JobRow).where(JobRow.application_url == TARGET_URL)
        ).scalar_one()
        assert job.company_name == "Drivetrain"
        assert job.title == "Business Analyst - Customer Platform"
        assert job.location == "India, Remote"
        assert job.application_url == TARGET_URL


def test_registering_the_same_url_twice_does_not_duplicate(tmp_path, monkeypatch, real_config):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    for _ in range(2):
        result = runner.invoke(
            app,
            [
                "applications", "target-add",
                "--url", TARGET_URL, "--company", "Acme Corp", "--title", "Synthetic Role",
            ],
        )
        assert result.exit_code == 0, result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        jobs = session.execute(
            select(JobRow).where(JobRow.application_url == TARGET_URL)
        ).scalars().all()
        assert len(jobs) == 1
        applications = session.execute(
            select(Application).where(Application.job_id == jobs[0].id)
        ).scalars().all()
        assert len(applications) == 1


def test_manual_job_source_is_created_disabled_so_jobs_scan_never_picks_it_up(
    tmp_path, monkeypatch, real_config
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(
        app,
        [
            "applications", "target-add",
            "--url", TARGET_URL, "--company", "Acme Corp", "--title", "Synthetic Role",
        ],
    )
    assert result.exit_code == 0, result.output

    engine = get_engine(f"sqlite:///{db_path}")
    with get_session_factory(engine)() as session:
        source = session.execute(
            select(JobSource).where(JobSource.name == "manual")
        ).scalar_one()
        assert source.enabled is False
        assert source.kind == "manual"


def test_target_add_never_imports_playwright_or_the_browser_stack():
    """Structural guarantee that this command cannot make a network/
    browser call: it never even imports the modules that could."""
    source = Path("src/job_agent/cli/main.py").read_text()
    target_add_start = source.index('@applications_app.command("target-add")')
    # Ends at the shared browser-command helpers, not "browser-preview"
    # itself -- those helpers (used by browser-preview/-approve/-fill)
    # legitimately reference BrowserApplicationProvider; that is not part
    # of target-add's own body.
    target_add_end = source.index("def _parse_answer_overrides")
    body = source[target_add_start:target_add_end]
    for forbidden in ("playwright", "BrowserSession", "BrowserApplicationProvider"):
        assert forbidden not in body

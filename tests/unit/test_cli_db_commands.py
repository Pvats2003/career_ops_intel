"""`job-agent db upgrade` / `job-agent db current` — local-activation-package
finding: nothing in this CLI ever ran Alembic. `init_db()` (used on every
other command's hot path) only calls `Base.metadata.create_all()`, which
creates missing tables but never ALTERs an existing table to add a column a
later migration introduces. A candidate who `git pull`s a new migration into
an already-populated database would otherwise hit "no such column" errors at
runtime with no documented fix. These commands are the real, explicit
migration path; `job-agent init` also runs the upgrade automatically at the
end of one-time setup.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from job_agent.cli.main import app
from job_agent.db.session import get_engine, init_db

runner = CliRunner()


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    db_path = tmp_path / "db_commands_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(real_config.env.candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "250")
    return db_path


def test_db_current_reports_head_revision_on_a_freshly_created_database(
    tmp_path, monkeypatch, real_config
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    result = runner.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert db_path.exists()

    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 0, result.output
    assert "Current revision" in result.output
    assert "none — never migrated" not in result.output


def test_db_current_on_a_never_migrated_database_reports_none(
    tmp_path, monkeypatch, real_config
):
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)  # create_all only — the exact gap `db upgrade` closes

    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 0, result.output
    assert "none — never migrated" in result.output


def test_db_upgrade_is_a_safe_no_op_when_already_current(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    first = runner.invoke(app, ["db", "upgrade"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["db", "upgrade"])
    assert second.exit_code == 0, second.output
    assert "up to date" in second.output


def test_serve_runs_the_alembic_upgrade_automatically_at_startup(
    tmp_path, monkeypatch, real_config
):
    """Cloud-deployment finding: a platform's start command is the ONLY
    thing that runs on every redeploy -- there is no separate interactive
    step to run `job-agent init`/`db upgrade` first. `serve()` must bring
    the schema up to date itself before it starts accepting requests, or a
    redeploy that adds a new alembic/versions/ migration would leave the
    live database silently out of date."""
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    result = runner.invoke(app, ["serve", "--no-scheduler"])
    assert result.exit_code == 0, result.output

    current = runner.invoke(app, ["db", "current"])
    assert current.exit_code == 0, current.output
    assert "none — never migrated" not in current.output
    assert db_path.exists()


def test_init_command_runs_the_alembic_upgrade_automatically(tmp_path, monkeypatch, real_config):
    # `init()` scaffolds against the literal `REPO_ROOT` (a real install has
    # exactly one `.env`), not `cfg.env.config_dir`/`candidate_dir` — and
    # `_alembic_config()` resolves `alembic.ini`/`alembic/` the same way. So
    # this test redirects `REPO_ROOT` into a throwaway directory that also
    # carries real copies of `alembic.ini`/`alembic/`, rather than either
    # invoking init() against the real repository's own `.env` or losing
    # alembic's ability to find its migration scripts.
    import job_agent.cli.main as cli_main

    real_repo_root = cli_main.REPO_ROOT
    cfg_dir = tmp_path / "config"
    candidate_dir = tmp_path / "candidate"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    shutil.copytree(real_config.env.candidate_dir, candidate_dir)
    shutil.copy(real_repo_root / ".env.example", tmp_path / ".env.example")
    shutil.copy(real_repo_root / "alembic.ini", tmp_path / "alembic.ini")
    shutil.copytree(real_repo_root / "alembic", tmp_path / "alembic")
    db_path = tmp_path / "init_test.db"

    monkeypatch.setattr(cli_main, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "Database schema is up to date." in result.output
    assert (tmp_path / ".env").exists()

    current = runner.invoke(app, ["db", "current"])
    assert current.exit_code == 0, current.output
    assert "none — never migrated" not in current.output

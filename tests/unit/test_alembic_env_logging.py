"""Regression test — local-activation-package finding: `alembic/env.py`
called `logging.config.fileConfig(config.config_file_name)` with its
default `disable_existing_loggers=True`. That silently disables every
Python logger that already exists at the moment Alembic's Python API runs
(`alembic.command.upgrade`/`current`, as used by `job-agent db upgrade`/
`db current`/`init`) for the rest of the process — a well-known Alembic
gotcha when its commands are invoked from inside a larger application
rather than only ever as `alembic`'s own short-lived CLI process.

Concretely: running `job-agent db upgrade` once in a process silently
killed all subsequent `job_agent.llm.cost` (and every other job_agent)
log output for the remainder of that process — cost logging (Part 17)
would go dark with no error, no warning, nothing.
"""

from __future__ import annotations

import logging

from alembic.config import Config as AlembicConfig

from alembic import command as alembic_command
from job_agent.config.loader import REPO_ROOT


def test_alembic_upgrade_does_not_disable_pre_existing_loggers(tmp_path, monkeypatch):
    # alembic/env.py overrides whatever `sqlalchemy.url` the caller sets
    # below with job_agent.config.loader.load_config().env.database_url --
    # its real, process-environment DATABASE_URL, not the caller's option.
    # Without pinning DATABASE_URL here, this test would silently run its
    # migration against the real repo's data/job_agent.db (harmless only
    # because that database happens to already be at head).
    db_path = tmp_path / "alembic_logging_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    sentinel_logger = logging.getLogger("job_agent.llm.cost")
    assert not sentinel_logger.disabled

    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    alembic_command.upgrade(cfg, "head")

    assert not sentinel_logger.disabled, (
        "alembic/env.py's fileConfig() call disabled a pre-existing logger — "
        "it must pass disable_existing_loggers=False"
    )


def test_alembic_env_normalizes_a_bare_postgresql_url(monkeypatch):
    """alembic/env.py builds its migration Engine independently of
    job_agent.db.session.get_engine() (via engine_from_config), so it has
    its own copy of the psycopg2->psycopg3 driver-name fix
    (normalize_database_url). Without it, a bare "postgresql://" URL --
    exactly what Neon/Render hand out -- would fail with
    ModuleNotFoundError('psycopg2') the instant a real migration ran,
    even though job-agent doctor/health (which go through get_engine())
    would look fine. Port 1 guarantees "connection refused", proving the
    normalization happened before any connection was attempted rather
    than failing on the driver import."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@127.0.0.1:1/nonexistent")

    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))

    try:
        alembic_command.upgrade(cfg, "head")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "alembic/env.py used the unnormalized bare postgresql:// URL "
            f"and tried to import psycopg2: {exc}"
        ) from exc
    except Exception:  # noqa: BLE001
        pass  # a real connection-refused error is expected and correct

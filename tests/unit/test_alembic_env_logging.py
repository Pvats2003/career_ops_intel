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


def test_alembic_upgrade_does_not_disable_pre_existing_loggers(tmp_path):
    sentinel_logger = logging.getLogger("job_agent.llm.cost")
    assert not sentinel_logger.disabled

    db_path = tmp_path / "alembic_logging_test.db"
    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    alembic_command.upgrade(cfg, "head")

    assert not sentinel_logger.disabled, (
        "alembic/env.py's fileConfig() call disabled a pre-existing logger — "
        "it must pass disable_existing_loggers=False"
    )

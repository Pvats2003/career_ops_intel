from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_agent.config.loader import load_config  # noqa: E402
from job_agent.db.models import Base  # noqa: E402
from job_agent.db.session import normalize_database_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which SILENTLY DISABLES
    # every logger that already exists at this point (e.g. job_agent's own
    # loggers) for the rest of the process — a well-known Alembic gotcha
    # when its migration commands are invoked from within a larger
    # long-lived application (`job-agent init`/`job-agent db upgrade` call
    # this via the Python API, in the same process as the rest of the
    # CLI) rather than only ever as its own short-lived `alembic` process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

try:
    app_config = load_config()
    # This engine is built independently of job_agent.db.session.get_engine()
    # (via engine_from_config below), so a bare postgres:// or postgresql://
    # connection string -- exactly what Neon/Render hand out -- would
    # otherwise bypass the same psycopg2->psycopg3 driver-name fix and
    # fail with "No module named 'psycopg2'" the moment a migration runs.
    config.set_main_option(
        "sqlalchemy.url", normalize_database_url(app_config.env.database_url)
    )
except Exception:
    # Fall back to whatever is in alembic.ini / -x url= if app config isn't
    # available yet (e.g. brand-new checkout before `job-agent init`).
    pass


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

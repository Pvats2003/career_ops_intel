"""Database engine/session management.

SQLite for V1 per BUILD PROMPT section 21. `init_db` creates the schema
directly via `Base.metadata.create_all` for local/dev use; the Alembic
migration in `alembic/versions/` is the source of truth for anything beyond
a fresh local database (upgrades, production-style deploys).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from job_agent.db.models import Base


def normalize_database_url(database_url: str) -> str:
    """Managed Postgres providers (Neon, Render, Heroku-style hosts) all
    hand out a bare `postgres://` or `postgresql://` connection string —
    never `postgresql+psycopg://`. SQLAlchemy's default driver for either
    bare scheme is psycopg2, which this project never installs (only
    `psycopg` — v3 — is a dependency); pasting a Neon/Render connection
    string in unmodified would otherwise fail immediately with
    `ModuleNotFoundError: No module named 'psycopg2'`. Rewriting the
    driver here means the connection string can be pasted in exactly as
    the provider gives it, with its query string (e.g. Neon's
    `?sslmode=require`) preserved untouched."""
    url = make_url(database_url)
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+psycopg")
    # `str(url)` masks the password (renders "***") -- fine for logging,
    # fatal here since this string is what actually opens the connection.
    return url.render_as_string(hide_password=False)


def get_engine(database_url: str) -> Engine:
    database_url = normalize_database_url(database_url)
    connect_args = {}
    is_sqlite = database_url.startswith("sqlite")
    if is_sqlite:
        connect_args = {"check_same_thread": False}
        if ":memory:" not in database_url:
            db_path = database_url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args=connect_args)

    if is_sqlite:
        # SQLite ignores FOREIGN KEY constraints unless explicitly told to
        # enforce them per-connection — without this, every ForeignKey(...)
        # in db/models.py is purely documentation, and an orphaned or
        # invalid reference (a job_matches row pointing at a deleted job,
        # a typo'd candidate_id) would insert silently instead of failing.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables that don't already exist. Idempotent."""
    Base.metadata.create_all(engine)

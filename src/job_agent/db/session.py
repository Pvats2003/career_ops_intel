"""Database engine/session management.

SQLite for V1 per BUILD PROMPT section 21. `init_db` creates the schema
directly via `Base.metadata.create_all` for local/dev use; the Alembic
migration in `alembic/versions/` is the source of truth for anything beyond
a fresh local database (upgrades, production-style deploys).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from job_agent.db.models import Base


def get_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if ":memory:" not in database_url:
            db_path = database_url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args=connect_args)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables that don't already exist. Idempotent."""
    Base.metadata.create_all(engine)

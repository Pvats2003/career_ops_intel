"""FastAPI dependencies: config, DB session, and the "current candidate".

`get_config()` deliberately calls `load_config()` fresh (not the
process-wide-cached `job_agent.config.loader.get_config()`) on every
request — the exact same choice `job_agent.cli.main` makes everywhere,
so a test can `monkeypatch.setenv(...)` per-test and this layer honors it
immediately, and so editing `config/*.yaml` on disk takes effect on the
next request without restarting the server.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from job_agent.candidate.parser import parse_candidate_profile
from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig, load_config
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db


def get_config() -> AppConfig:
    return load_config()


# `Annotated[X, Depends(...)]` parameters (rather than `x: X =
# Depends(...)`) — the FastAPI-recommended style, and it also sidesteps
# ruff's B008 ("no function call in argument defaults"), which doesn't
# know `Depends(...)` is meant to be re-evaluated per request. Defined
# right after each dependency function so a later one can build on an
# earlier one's alias (`get_session` on `ConfigDep`, `get_candidate` on
# both) without repeating `Depends(...)` in a bare default anywhere.
ConfigDep = Annotated[AppConfig, Depends(get_config)]


@lru_cache(maxsize=8)
def _cached_engine(database_url: str) -> Engine:
    """One SQLAlchemy `Engine` (and connection pool) per distinct
    `database_url` for the life of this process — recreating an `Engine`
    on every single request would be wasteful, but the cache key is the
    URL itself, so a test that points `DATABASE_URL` at a fresh tmp_path
    file still gets its own isolated engine, never a stale one from a
    previous test's database."""
    engine = get_engine(database_url)
    init_db(engine)
    return engine


def get_session(config: ConfigDep) -> Generator[Session, None, None]:
    engine = _cached_engine(config.env.database_url)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_candidate(session: SessionDep, config: ConfigDep) -> tuple[CandidateProfile, int]:
    """The exact same `parse candidate/*.md -> save_candidate_profile`
    idempotent-upsert sequence every `job_agent.cli.main` command already
    runs before touching the DB — the profile files on disk stay the one
    source of truth, and `save_candidate_profile` is a no-op re-save when
    nothing changed. Raises `CandidateParseError`/`ResumeExtractionError`
    (via callers) exactly like the CLI does; routes translate those to
    HTTP 422 rather than a raw 500."""
    profile = parse_candidate_profile(config)
    candidate_id = save_candidate_profile(session, profile)
    session.commit()
    return profile, candidate_id


CandidateDep = Annotated[tuple[CandidateProfile, int], Depends(get_candidate)]

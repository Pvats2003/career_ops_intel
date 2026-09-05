from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from job_agent.db.models import Candidate, Job, JobMatch, JobSource
from job_agent.db.session import get_engine, get_session_factory, init_db, normalize_database_url


def test_sqlite_foreign_keys_are_enforced():
    """Every ForeignKey(...) in db/models.py is meaningless unless SQLite is
    told to enforce it per-connection. Without this, an orphaned/typo'd
    reference (e.g. a job_matches row pointing at a candidate_id that
    doesn't exist) would insert silently instead of failing."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        session.add(
            JobMatch(
                job_id=999999,
                candidate_id=999999,
                overall_score=50,
                decision="SKIP",
                reasoning="orphaned reference test",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_valid_references_still_insert_fine():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        source = JobSource(name="greenhouse", kind="ats_api", enabled=True)
        session.add(source)
        session.flush()
        job = Job(
            source_id=source.id, source_job_id="1", company_name="Acme",
            title="Product Analyst", application_url="https://x.test/1",
            job_fingerprint="fp1",
        )
        candidate = Candidate(
            name="Test", email="t@example.com", phone="+1", linkedin="li",
            current_location="Remote", parsed_at=datetime.now(UTC),
        )
        session.add_all([job, candidate])
        session.flush()
        session.add(
            JobMatch(
                job_id=job.id, candidate_id=candidate.id, overall_score=80,
                decision="REVIEW", reasoning="ok",
            )
        )
        session.commit()  # must not raise


# --- normalize_database_url: Neon/Render compatibility ---------------------
# Managed Postgres providers (Neon, Render, Heroku-style hosts) all hand out
# a bare "postgres://" or "postgresql://" connection string. SQLAlchemy's
# default driver for either is psycopg2, which this project never installs
# (only psycopg -- v3). Pasting a real Neon connection string in unmodified
# used to fail immediately with ModuleNotFoundError: No module named
# 'psycopg2' the moment anything tried to connect.


def test_bare_postgresql_scheme_is_rewritten_to_psycopg3():
    result = normalize_database_url("postgresql://user:pw@host:5432/db")
    assert result == "postgresql+psycopg://user:pw@host:5432/db"


def test_heroku_style_postgres_scheme_is_rewritten_to_psycopg3():
    result = normalize_database_url("postgres://user:pw@host:5432/db")
    assert result == "postgresql+psycopg://user:pw@host:5432/db"


def test_neon_query_string_is_preserved_exactly():
    result = normalize_database_url(
        "postgresql://user:pw@ep-cool-1234.us-east-2.aws.neon.tech/neondb?sslmode=require"
    )
    assert result == (
        "postgresql+psycopg://user:pw@ep-cool-1234.us-east-2.aws.neon.tech/neondb"
        "?sslmode=require"
    )


def test_already_explicit_psycopg_driver_is_left_alone():
    result = normalize_database_url("postgresql+psycopg://user:pw@host/db")
    assert result == "postgresql+psycopg://user:pw@host/db"


def test_sqlite_urls_are_never_touched():
    assert normalize_database_url("sqlite:///./data/job_agent.db") == (
        "sqlite:///./data/job_agent.db"
    )
    assert normalize_database_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_password_is_not_masked_in_the_normalized_url():
    """`str(url)` (SQLAlchemy's default __str__) renders "***" for the
    password -- fine for logging, fatal here since this string is what
    actually opens the connection. A silent regression to `str(url)`
    would make every real Postgres connection attempt fail auth."""
    result = normalize_database_url("postgresql://user:s3cret@host/db")
    assert "s3cret" in result
    assert "***" not in result


def test_get_engine_accepts_a_bare_postgresql_url_without_crashing():
    """get_engine() must not raise ModuleNotFoundError('psycopg2') just
    from building the Engine object for a bare postgresql:// URL -- the
    exact scheme Neon/Render hand out. (Building an Engine is lazy and
    doesn't itself require a reachable server; only .connect() would.)"""
    engine = get_engine("postgresql://user:pw@127.0.0.1:1/nonexistent")
    assert engine.dialect.driver == "psycopg"

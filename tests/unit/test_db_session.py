from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from job_agent.db.models import Candidate, Job, JobMatch, JobSource
from job_agent.db.session import get_engine, get_session_factory, init_db


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

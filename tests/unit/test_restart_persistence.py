"""Restart/persistence verification — local-activation-package finding: every
important piece of state (candidate profile, jobs, matches, applications)
must survive a real process restart, not just live in an in-memory sqlite
connection that happens to outlive the test.

This test never reuses a live `Session`/`Engine` across the "restart" —
it disposes the first `Engine` (closing its connection pool, the closest
in-process approximation of the OS actually killing the process) and opens
a brand-new `Engine` against the same file-backed database, exactly as
`job-agent serve` does on every real launch.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from job_agent.db.models import Application, Candidate, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.repository import get_or_create_job_source, upsert_job
from job_agent.jobs.schema import FreshnessStatus, Job, RemoteType


def test_candidate_job_match_and_application_survive_a_full_restart(
    tmp_path: Path, real_profile
):
    db_path = tmp_path / "restart_persistence.db"
    database_url = f"sqlite:///{db_path}"

    # --- "Session 1": first launch, real state gets created and committed ---
    engine_one = get_engine(database_url)
    init_db(engine_one)
    session_factory_one = get_session_factory(engine_one)

    with session_factory_one() as session:
        candidate_id = save_candidate_profile(session, real_profile)

        source_row = get_or_create_job_source(
            session, name="restart-test-source", kind="search_api", enabled=True
        )
        job = Job(
            source=source_row.name,
            source_job_id="restart-persistence-job-1",
            company="[TEST-ONLY] Persistence Co",
            title="[TEST-ONLY] Restart Persistence Analyst",
            remote_type=RemoteType.REMOTE,
            application_url="https://example.test/restart-persistence-job-1",
        )
        job_row, created = upsert_job(
            session, job, source_row=source_row, freshness_status=FreshnessStatus.NEW
        )
        assert created
        job_id = job_row.id

        match = JobMatch(
            job_id=job_id,
            candidate_id=candidate_id,
            overall_score=87.5,
            decision="APPLY",
        )
        session.add(match)
        session.flush()
        match_id = match.id

        application = Application(
            job_id=job_id,
            candidate_id=candidate_id,
            status="DISCOVERED",
            match_score=87.5,
            pipeline_stage="SAVED",
            notes="[TEST-ONLY] restart persistence check",
        )
        session.add(application)
        session.flush()
        application_id = application.id

        session.commit()

    # Simulate the process actually exiting: dispose the connection pool so
    # nothing about "session 1" survives except what's on disk.
    engine_one.dispose()

    # --- "Session 2": a fresh restart, brand-new Engine/session factory ---
    engine_two = get_engine(database_url)
    session_factory_two = get_session_factory(engine_two)

    with session_factory_two() as session:
        candidate = session.get(Candidate, candidate_id)
        assert candidate is not None
        assert candidate.name == real_profile.identity_name.value
        assert candidate.email == real_profile.contact_email.value

        job_row = session.get(JobRow, job_id)
        assert job_row is not None
        assert job_row.title == "[TEST-ONLY] Restart Persistence Analyst"
        assert job_row.company_name == "[TEST-ONLY] Persistence Co"

        match_row = session.get(JobMatch, match_id)
        assert match_row is not None
        assert match_row.overall_score == 87.5
        assert match_row.decision == "APPLY"

        application_row = session.get(Application, application_id)
        assert application_row is not None
        assert application_row.status == "DISCOVERED"
        assert application_row.pipeline_stage == "SAVED"
        assert application_row.notes == "[TEST-ONLY] restart persistence check"

        # Confirm this really is a durable row count, not an artifact of
        # the specific ids used above.
        assert session.execute(select(Candidate)).scalars().all()
        assert session.execute(select(JobRow)).scalars().all()
        assert session.execute(select(JobMatch)).scalars().all()
        assert session.execute(select(Application)).scalars().all()

    engine_two.dispose()

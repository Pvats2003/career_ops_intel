"""Job lifecycle (ACTIVE/CLOSED/EXPIRED) and source-health tracking —
Career OS Phase 8 section 7. Uses the same in-memory sqlite + real
`scan_source`/`run_scan` pattern as `test_job_service.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from job_agent.config.loader import load_config
from job_agent.db.models import Base
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobSource as JobSourceRow
from job_agent.db.session import get_engine
from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.service import mark_missing_jobs_closed, mark_stale_jobs_expired, scan_source
from job_agent.jobs.source import HealthCheckResult, JobSource
from job_agent.jobs.sources.greenhouse import GreenhouseJobSource
from job_agent.net.http_client import ResilientHttpClient


@pytest.fixture
def session_factory():
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def real_config():
    return load_config()


class _FixedJobSource(JobSource):
    """A minimal, directly-controllable JobSource for lifecycle tests —
    returns exactly the raw postings passed in, never touches a network."""

    name = "fixed"

    def __init__(self, postings: list[dict]) -> None:
        self._postings = postings

    def search(self) -> list[dict]:
        return self._postings

    def normalize(self, raw: dict) -> Job:
        return Job(
            source=self.name,
            source_job_id=raw["id"],
            company="Acme",
            title=raw["title"],
            remote_type=RemoteType.UNKNOWN,
            application_url=f"https://example.test/{raw['id']}",
        )

    def get_posted_time(self, raw: dict) -> None:
        return None

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(healthy=True, detail="ok", checked_at=datetime.now(UTC))


def _http(handler) -> ResilientHttpClient:
    return ResilientHttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_healthy_scan_records_source_health(session_factory, real_config):
    def handler(request):
        return httpx.Response(200, json={"jobs": []})

    with session_factory() as session:
        src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
        scan_source(session, real_config, src)
        session.commit()

        row = session.execute(
            select(JobSourceRow).where(JobSourceRow.name == "greenhouse")
        ).scalar_one()
        assert row.last_health_status == "healthy"
        assert row.last_health_check_at is not None


def test_failed_scan_records_unhealthy_status(session_factory, real_config):
    def handler(request):
        raise httpx.ConnectError("boom")

    with session_factory() as session:
        src = GreenhouseJobSource("acme", "Acme Inc", _http(handler))
        scan_source(session, real_config, src)
        session.commit()

        row = session.execute(
            select(JobSourceRow).where(JobSourceRow.name == "greenhouse")
        ).scalar_one()
        assert row.last_health_status is not None
        assert row.last_health_status.startswith("unhealthy")


def test_job_disappearing_from_a_full_rescan_gets_closed(session_factory, real_config):
    with session_factory() as session:
        # First scan: two jobs present.
        src1 = _FixedJobSource([{"id": "1", "title": "A"}, {"id": "2", "title": "B"}])
        scan_source(session, real_config, src1)
        session.commit()

        jobs = list(session.execute(select(JobRow)).scalars())
        assert len(jobs) == 2
        assert all(j.lifecycle_status == "ACTIVE" for j in jobs)

        # Second scan: only job "1" still listed -> job "2" should close.
        src2 = _FixedJobSource([{"id": "1", "title": "A"}])
        scan_source(session, real_config, src2)
        session.commit()

        by_id = {j.source_job_id: j for j in session.execute(select(JobRow)).scalars()}
        assert by_id["1"].lifecycle_status == "ACTIVE"
        assert by_id["2"].lifecycle_status == "CLOSED"


def test_empty_scan_result_never_mass_closes_active_jobs(session_factory, real_config):
    """A transient empty/degraded response must never be read as 'every
    job at this source just closed' — see scan_source's own guard."""
    with session_factory() as session:
        src1 = _FixedJobSource([{"id": "1", "title": "A"}])
        scan_source(session, real_config, src1)
        session.commit()

        src_empty = _FixedJobSource([])
        scan_source(session, real_config, src_empty)
        session.commit()

        job = session.execute(select(JobRow)).scalars().one()
        assert job.lifecycle_status == "ACTIVE"


def test_already_closed_job_is_never_touched_by_a_later_scan(session_factory, real_config):
    with session_factory() as session:
        src1 = _FixedJobSource([{"id": "1", "title": "A"}, {"id": "2", "title": "B"}])
        scan_source(session, real_config, src1)
        session.commit()

        src2 = _FixedJobSource([{"id": "1", "title": "A"}])
        scan_source(session, real_config, src2)  # closes "2"
        session.commit()

        # A third scan that also doesn't list "2" must not re-process it
        # or raise — it's already CLOSED, mark_missing_jobs_closed only
        # ever touches ACTIVE rows.
        src3 = _FixedJobSource([{"id": "1", "title": "A"}])
        scan_source(session, real_config, src3)
        session.commit()

        by_id = {j.source_job_id: j for j in session.execute(select(JobRow)).scalars()}
        assert by_id["2"].lifecycle_status == "CLOSED"


def test_mark_stale_jobs_expired_only_touches_old_active_jobs(session_factory):
    with session_factory() as session:
        fresh = JobRow(
            company_name="Acme", title="Fresh", application_url="https://example.test/fresh",
            job_fingerprint="fp-fresh", lifecycle_status="ACTIVE",
            last_checked_at=datetime.now(UTC),
        )
        stale = JobRow(
            company_name="Acme", title="Stale", application_url="https://example.test/stale",
            job_fingerprint="fp-stale", lifecycle_status="ACTIVE",
            last_checked_at=datetime.now(UTC) - timedelta(days=90),
        )
        already_closed = JobRow(
            company_name="Acme", title="Closed", application_url="https://example.test/closed",
            job_fingerprint="fp-closed", lifecycle_status="CLOSED",
            last_checked_at=datetime.now(UTC) - timedelta(days=90),
        )
        session.add_all([fresh, stale, already_closed])
        session.commit()

        expired_count = mark_stale_jobs_expired(session, max_active_days=60)
        session.commit()

        assert expired_count == 1
        assert fresh.lifecycle_status == "ACTIVE"
        assert stale.lifecycle_status == "EXPIRED"
        assert already_closed.lifecycle_status == "CLOSED"  # never touched


def test_mark_missing_jobs_closed_is_scoped_to_the_given_source(session_factory, real_config):
    """A job belonging to a DIFFERENT source must never be closed just
    because this source's scan didn't mention its source_job_id."""
    with session_factory() as session:
        src_a = _FixedJobSource([{"id": "shared-id", "title": "A"}])
        src_a.name = "source_a"
        scan_source(session, real_config, src_a)
        session.commit()

        source_a_row = session.execute(
            select(JobSourceRow).where(JobSourceRow.name == "source_a")
        ).scalar_one()

        src_b = _FixedJobSource([{"id": "different-id", "title": "B"}])
        src_b.name = "source_b"
        scan_source(session, real_config, src_b)
        session.commit()

        closed = mark_missing_jobs_closed(session, source_a_row, seen_source_job_ids=set())
        session.commit()
        assert closed == 1  # only source_a's own job, never source_b's

        jobs = list(session.execute(select(JobRow)).scalars())
        assert len(jobs) == 2

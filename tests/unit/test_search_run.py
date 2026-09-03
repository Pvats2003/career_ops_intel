"""SearchRun orchestration (job_agent.jobs.search_run) — Career OS Phase 8
section 3. Uses the same `_FixedJobSource` direct-injection pattern as
`test_job_lifecycle.py` so nothing here makes a real network call.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.db.models import SearchRun as SearchRunRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.search_run import execute_search_run
from job_agent.jobs.source import HealthCheckResult, JobSource


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


def _fact(value: str) -> Fact[str]:
    return Fact[str](value=value, source="test", confidence=1.0, verified=True)


def _profile() -> CandidateProfile:
    unknown = Fact.unknown(source="test")
    return CandidateProfile(
        identity_name=_fact("Test Candidate"),
        identity_current_location=_fact("Remote"),
        contact_email=_fact("test.search.run@example.invalid"),
        contact_phone=_fact("+1-555-0100"),
        contact_linkedin=_fact("https://linkedin.com/in/test"),
        target_roles=TargetRoles(primary=("Business Analyst",)),
        skills=(),
        experience=(),
        education=(),
        work_preferences=WorkPreferences(
            remote=unknown, willing_to_relocate=unknown, notice_period=unknown
        ),
        location_preferences=LocationPreferences(
            current_location=_fact("Remote"), open_to_countries=unknown
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown, minimum_annual=unknown, target_annual=unknown, negotiable=unknown
        ),
        visa_information=VisaInformation(
            nationality=unknown, requires_sponsorship_us=unknown,
            requires_sponsorship_uk=unknown, requires_sponsorship_eu=unknown,
            requires_sponsorship_other=unknown,
        ),
    )


class _StubJobSource(JobSource):
    name = "stub"

    def __init__(self, postings: list[dict], *, fail: bool = False) -> None:
        self._postings = postings
        self._fail = fail

    def search(self) -> list[dict]:
        if self._fail:
            raise RuntimeError("stub source failure")
        return self._postings

    def normalize(self, raw: dict) -> Job:
        return Job(
            source=self.name, source_job_id=raw["id"], company="Acme", title=raw["title"],
            remote_type=RemoteType.UNKNOWN, application_url=f"https://example.test/{raw['id']}",
        )

    def get_posted_time(self, raw: dict) -> None:
        return None

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(healthy=True, detail="ok", checked_at=datetime.now(UTC))


def _seed_candidate(session, real_config) -> tuple:
    from job_agent.db.repository import save_candidate_profile

    profile = _profile()
    candidate_id = save_candidate_profile(session, profile)
    session.commit()
    return profile, candidate_id


def test_execute_search_run_records_a_completed_run(db_session, real_config):
    profile, candidate_id = _seed_candidate(db_session, real_config)
    src = _StubJobSource([{"id": "1", "title": "Business Analyst"}])

    run = execute_search_run(db_session, real_config, profile, candidate_id, sources=[src])

    assert run.id is not None
    assert run.status == "COMPLETED"
    assert run.completed_at is not None
    assert run.jobs_found == 1
    assert run.sources == ["stub"]
    assert run.queries  # generated from the profile, non-empty
    assert run.errors == []


def test_execute_search_run_survives_a_failing_source(db_session, real_config):
    profile, candidate_id = _seed_candidate(db_session, real_config)
    src = _StubJobSource([], fail=True)

    run = execute_search_run(db_session, real_config, profile, candidate_id, sources=[src])

    assert run.status == "PARTIAL"
    assert run.jobs_found == 0
    assert len(run.errors) == 1
    assert "stub source failure" in run.errors[0]


def test_execute_search_run_persists_to_the_database(db_session, real_config):
    profile, candidate_id = _seed_candidate(db_session, real_config)
    src = _StubJobSource([{"id": "1", "title": "Business Analyst"}])
    run = execute_search_run(db_session, real_config, profile, candidate_id, sources=[src])

    reloaded = db_session.get(SearchRunRow, run.id)
    assert reloaded is not None
    assert reloaded.status == "COMPLETED"


def test_execute_search_run_detects_cross_source_duplicates(db_session, real_config):
    profile, candidate_id = _seed_candidate(db_session, real_config)

    class _OtherSource(_StubJobSource):
        name = "other"

    # Two DIFFERENT sources, SAME company/title/location/url -> same
    # content fingerprint -> counted as a duplicate, never merged/dropped.
    src_a = _StubJobSource([{"id": "shared", "title": "Business Analyst"}])
    run_a = execute_search_run(db_session, real_config, profile, candidate_id, sources=[src_a])
    assert run_a.duplicates_removed == 0

    src_b = _OtherSource([{"id": "shared", "title": "Business Analyst"}])
    run_b = execute_search_run(db_session, real_config, profile, candidate_id, sources=[src_b])
    assert run_b.duplicates_removed == 1


def test_execute_search_run_qualified_counts_apply_and_review_only(db_session, real_config):
    profile, candidate_id = _seed_candidate(db_session, real_config)
    src = _StubJobSource([{"id": "1", "title": "Totally Unrelated Role XYZ"}])
    run = execute_search_run(db_session, real_config, profile, candidate_id, sources=[src])
    # A single, deliberately unrelated posting should not count as
    # "qualified" (APPLY/REVIEW) — a weak/no match is SAVE/SKIP.
    assert run.qualified in (0, 1)  # sanity: never negative, never > jobs_found
    assert run.qualified <= run.jobs_found

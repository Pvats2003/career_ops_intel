from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.db.models import Candidate, JobMatch, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.llm.provider import LLMCallMetadata, LLMProvider, NullLLMProvider
from job_agent.matching.schema import Decision
from job_agent.matching.service import match_job, run_matching


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture()
def source_row(db_session):
    row = JobSource(name="greenhouse", kind="ats_api", enabled=True)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def candidate_row(db_session):
    # A real row is required now that SQLite foreign keys are enforced
    # (db.session.get_engine) — job_matches.candidate_id must reference an
    # actual candidate, matching how the real `jobs match` CLI command
    # always runs `save_candidate_profile` before `run_matching`.
    row = Candidate(
        name="Test Candidate", email="test@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _job_row(source_row, **overrides) -> JobRow:
    defaults = dict(
        source_id=source_row.id,
        source_job_id="1",
        company_name="Acme Inc",
        title="Associate Product Manager",
        description="Entry level APM. SQL, Excel, Agile/Scrum a plus.",
        location="Manipal, Karnataka, India",
        remote_type="onsite",
        application_url="https://x.test/1",
        job_fingerprint="fp1",
    )
    defaults.update(overrides)
    return JobRow(**defaults)


class _StubLLM(LLMProvider):
    def __init__(self):
        self.calls = 0

    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        self.calls += 1
        result = schema(
            role_alignment_score=90, experience_similarity_score=70, project_relevance_score=60,
            reasoning="ok",
        )
        meta = LLMCallMetadata(
            provider="fake", model="fake-model", prompt_version=prompt_version,
            input_tokens=1, output_tokens=1, latency_ms=1.0,
        )
        return result, meta


def test_match_job_skips_semantic_for_excluded_role(
    db_session, source_row, real_profile, real_config
):
    job = _job_row(source_row, title="Senior Product Manager")  # excluded in config/profile.yaml
    db_session.add(job)
    db_session.flush()
    llm = _StubLLM()
    outcome = match_job(real_profile, real_config, job, llm)
    assert outcome.semantic_call_made is False
    assert llm.calls == 0
    assert outcome.result.decision == Decision.SKIP


def test_match_job_skips_semantic_for_very_low_deterministic_score(
    db_session, source_row, real_profile, real_config
):
    job = _job_row(
        source_row,
        title="Data Warehouse Architect",
        description="Tableau, Power BI, and Looker required. 10+ years of experience.",
        location="Unspecified",
        remote_type="onsite",
    )
    db_session.add(job)
    db_session.flush()
    llm = _StubLLM()
    outcome = match_job(real_profile, real_config, job, llm)
    assert outcome.semantic_call_made is False
    assert llm.calls == 0


def test_match_job_calls_semantic_for_promising_job(
    db_session, source_row, real_profile, real_config
):
    job = _job_row(source_row)
    db_session.add(job)
    db_session.flush()
    llm = _StubLLM()
    outcome = match_job(real_profile, real_config, job, llm)
    assert outcome.semantic_call_made is True
    assert llm.calls == 1
    assert outcome.result.semantic_available is True


def test_run_matching_persists_and_returns_outcomes(
    db_session, source_row, candidate_row, real_profile, real_config
):
    job1 = _job_row(source_row, source_job_id="1")
    job2 = _job_row(source_row, source_job_id="2", title="Business Analyst")
    db_session.add_all([job1, job2])
    db_session.flush()

    outcomes = run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id, llm=NullLLMProvider()
    )
    assert len(outcomes) == 2
    assert db_session.query(JobMatch).count() == 2


def test_run_matching_with_job_ids_filter(
    db_session, source_row, candidate_row, real_profile, real_config
):
    job1 = _job_row(source_row, source_job_id="1")
    job2 = _job_row(source_row, source_job_id="2", title="Business Analyst")
    db_session.add_all([job1, job2])
    db_session.flush()

    outcomes = run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id,
        llm=NullLLMProvider(), job_ids=[job1.id],
    )
    assert len(outcomes) == 1
    assert outcomes[0].job_id == job1.id


def test_run_matching_survives_one_bad_job_in_the_batch(
    db_session, source_row, candidate_row, real_profile, real_config, monkeypatch
):
    """A single job that raises during matching must not abort the whole
    batch — the other jobs' matches must still be computed and persisted."""
    import job_agent.matching.service as service_module

    job1 = _job_row(source_row, source_job_id="1")
    job2 = _job_row(source_row, source_job_id="2", title="Business Analyst")
    job3 = _job_row(source_row, source_job_id="3", title="Data Analyst")
    db_session.add_all([job1, job2, job3])
    db_session.flush()

    real_match_job = service_module.match_job

    def _flaky_match_job(profile, config, job_row, llm):
        if job_row.id == job2.id:
            raise RuntimeError("simulated unexpected failure for this job only")
        return real_match_job(profile, config, job_row, llm)

    monkeypatch.setattr(service_module, "match_job", _flaky_match_job)

    outcomes = run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id, llm=NullLLMProvider()
    )

    assert {o.job_id for o in outcomes} == {job1.id, job3.id}
    assert db_session.query(JobMatch).count() == 2


def test_run_matching_reuses_cached_match_no_llm_call_when_nothing_changed(
    db_session, source_row, candidate_row, real_profile, real_config
):
    """Career OS Phase 16 cost control: an unchanged job + unchanged
    profile + unchanged scoring config on a second run must reuse the
    first run's JobMatch, never pay for a second LLM call."""
    job = _job_row(source_row)
    db_session.add(job)
    db_session.flush()

    llm = _StubLLM()
    run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id, llm=llm,
        job_ids=[job.id],
    )
    calls_after_first_run = llm.calls
    assert calls_after_first_run == 1
    assert db_session.query(JobMatch).count() == 1

    outcomes = run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id, llm=llm,
        job_ids=[job.id],
    )
    assert llm.calls == calls_after_first_run
    assert db_session.query(JobMatch).count() == 1
    assert outcomes[0].semantic_call_made is False


def test_run_matching_recomputes_when_job_description_changes(
    db_session, source_row, candidate_row, real_profile, real_config
):
    job = _job_row(source_row)
    db_session.add(job)
    db_session.flush()

    llm = _StubLLM()
    run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id, llm=llm,
        job_ids=[job.id],
    )
    assert llm.calls == 1

    job.description = "Completely different posting text now, still promising."
    db_session.flush()

    run_matching(
        db_session, real_config, real_profile, candidate_id=candidate_row.id, llm=llm,
        job_ids=[job.id],
    )
    assert llm.calls == 2
    assert db_session.query(JobMatch).count() == 2

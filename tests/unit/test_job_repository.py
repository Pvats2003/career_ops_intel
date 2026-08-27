from __future__ import annotations

import pytest

from job_agent.db.models import Company
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.repository import (
    find_by_fingerprint,
    get_or_create_company,
    get_or_create_job_source,
    upsert_job,
)
from job_agent.jobs.schema import FreshnessStatus, Job


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


def _source_row(session):
    return get_or_create_job_source(session, name="greenhouse", kind="ats_api", enabled=True)


def _job(**overrides) -> Job:
    defaults = dict(
        source="greenhouse",
        source_job_id="111",
        company="Acme Inc",
        title="Associate Product Manager",
        location="Remote - US",
        application_url="https://boards.greenhouse.io/acme/jobs/111",
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_get_or_create_job_source_is_idempotent(db_session):
    row1 = get_or_create_job_source(db_session, name="greenhouse", kind="ats_api", enabled=True)
    row2 = get_or_create_job_source(db_session, name="greenhouse", kind="ats_api", enabled=True)
    assert row1.id == row2.id


def test_get_or_create_company_is_idempotent(db_session):
    c1 = get_or_create_company(db_session, "Acme Inc")
    c2 = get_or_create_company(db_session, "Acme Inc")
    assert c1.id == c2.id
    assert db_session.query(Company).count() == 1


def test_upsert_job_creates_then_updates(db_session):
    source_row = _source_row(db_session)

    row, created = upsert_job(
        db_session, _job(), source_row=source_row, freshness_status=FreshnessStatus.NEW
    )
    db_session.commit()
    assert created is True
    first_seen = row.first_seen_at
    assert db_session.query(JobRow).count() == 1

    row2, created2 = upsert_job(
        db_session,
        _job(title="Associate Product Manager II"),
        source_row=source_row,
        freshness_status=FreshnessStatus.OLD,
    )
    db_session.commit()
    assert created2 is False
    assert row2.id == row.id
    assert row2.title == "Associate Product Manager II"
    assert row2.freshness_status == FreshnessStatus.OLD.value
    assert row2.first_seen_at == first_seen  # never overwritten
    assert db_session.query(JobRow).count() == 1


def test_upsert_job_different_source_job_id_creates_new_row(db_session):
    source_row = _source_row(db_session)
    upsert_job(
        db_session, _job(source_job_id="1"), source_row=source_row,
        freshness_status=FreshnessStatus.NEW,
    )
    upsert_job(
        db_session, _job(source_job_id="2"), source_row=source_row,
        freshness_status=FreshnessStatus.NEW,
    )
    db_session.commit()
    assert db_session.query(JobRow).count() == 2


def test_find_by_fingerprint(db_session):
    source_row = _source_row(db_session)
    row, _ = upsert_job(
        db_session, _job(), source_row=source_row, freshness_status=FreshnessStatus.NEW
    )
    db_session.commit()
    matches = find_by_fingerprint(db_session, row.job_fingerprint)
    assert len(matches) == 1
    assert matches[0].id == row.id

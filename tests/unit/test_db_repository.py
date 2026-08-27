from __future__ import annotations

import pytest

from job_agent.candidate.parser import parse_candidate_profile
from job_agent.db.models import Candidate, CandidateFact, Experience, Project, Skill
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db


@pytest.fixture()
def db_session(real_config):
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


def test_save_candidate_profile_creates_rows(real_config, db_session):
    profile = parse_candidate_profile(real_config)
    candidate_id = save_candidate_profile(db_session, profile)

    assert db_session.get(Candidate, candidate_id) is not None
    assert db_session.query(Skill).filter_by(candidate_id=candidate_id).count() == len(
        profile.skills
    )
    assert db_session.query(Experience).filter_by(candidate_id=candidate_id).count() == len(
        profile.experience
    )
    assert db_session.query(Project).filter_by(candidate_id=candidate_id).count() == len(
        profile.projects
    )
    assert db_session.query(CandidateFact).filter_by(candidate_id=candidate_id).count() > 0


def test_save_candidate_profile_is_idempotent_on_rerun(real_config, db_session):
    profile = parse_candidate_profile(real_config)
    id1 = save_candidate_profile(db_session, profile)
    id2 = save_candidate_profile(db_session, profile)

    assert id1 == id2
    assert db_session.query(Candidate).count() == 1
    assert db_session.query(Skill).filter_by(candidate_id=id1).count() == len(profile.skills)


def test_all_stored_facts_carry_provenance(real_config, db_session):
    profile = parse_candidate_profile(real_config)
    candidate_id = save_candidate_profile(db_session, profile)

    for skill_row in db_session.query(Skill).filter_by(candidate_id=candidate_id).all():
        assert skill_row.source
        assert 0.0 <= skill_row.confidence <= 1.0

    for fact_row in db_session.query(CandidateFact).filter_by(candidate_id=candidate_id).all():
        assert fact_row.source

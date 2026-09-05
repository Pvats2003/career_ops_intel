"""Dashboard performance forensic fix — `save_candidate_profile()` used to
unconditionally delete and reinsert every fact/skill/experience/project row
on EVERY call, which in production meant every one of the ~8 concurrently-
fired Dashboard requests (each depending on `CandidateDep`) rewrote the
candidate's entire knowledge base on every single page view. These tests
prove the new fingerprint-gated no-op path: identical content -> zero
writes; changed content -> exactly one full resync, correctly.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from job_agent.candidate.schema import Fact
from job_agent.db.models import Candidate, Experience, Project, Skill
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.resume.versioning import compute_profile_hash


@contextmanager
def _counting_writes(engine, *table_names: str):
    """Counts INSERT/UPDATE/DELETE statements touching any of `table_names`."""
    counts = {"n": 0}

    def _listener(conn, cursor, statement, *args):
        upper = statement.lstrip().upper()
        if not (
            upper.startswith("INSERT")
            or upper.startswith("UPDATE")
            or upper.startswith("DELETE")
        ):
            return
        if any(name in statement for name in table_names):
            counts["n"] += 1

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


@pytest.fixture()
def engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture()
def session(engine):
    factory = get_session_factory(engine)
    with factory() as s:
        yield s


def test_first_persistence_creates_expected_rows(real_profile, session):
    candidate_id = save_candidate_profile(session, real_profile)

    candidate = session.get(Candidate, candidate_id)
    assert candidate is not None
    assert candidate.profile_fingerprint == compute_profile_hash(real_profile)
    assert (
        session.query(Skill).filter_by(candidate_id=candidate_id).count()
        == len(real_profile.skills)
    )
    assert (
        session.query(Experience).filter_by(candidate_id=candidate_id).count()
        == len(real_profile.experience)
    )
    assert (
        session.query(Project).filter_by(candidate_id=candidate_id).count()
        == len(real_profile.projects)
    )


def test_second_identical_persistence_is_a_true_noop(real_profile, session, engine):
    save_candidate_profile(session, real_profile)

    with _counting_writes(
        engine, "skills", "experiences", "projects", "candidate_facts", "candidate"
    ) as counts:
        candidate_id = save_candidate_profile(session, real_profile)

    assert counts["n"] == 0, (
        f"expected zero writes for an unchanged profile, got {counts['n']} — "
        f"looks like the unconditional delete/reinsert regressed"
    )
    candidate = session.get(Candidate, candidate_id)
    assert (
        session.query(Skill).filter_by(candidate_id=candidate_id).count()
        == len(real_profile.skills)
    )
    assert candidate.profile_fingerprint == compute_profile_hash(real_profile)


def test_identical_profile_content_produces_identical_fingerprint(real_profile):
    # parsed_at always differs between two "identical" parses in production
    # (it's `datetime.now(UTC)` at parse time) — the hash must ignore it.
    import datetime as _dt

    copy_with_different_parsed_at = real_profile.model_copy(
        update={"parsed_at": real_profile.parsed_at + _dt.timedelta(days=1)}
    )
    assert compute_profile_hash(real_profile) == compute_profile_hash(copy_with_different_parsed_at)


def test_changed_profile_triggers_full_resync(real_profile, session, engine):
    save_candidate_profile(session, real_profile)

    changed = real_profile.model_copy(
        update={
            "identity_current_location": Fact(
                value="A Different City", source="test", confidence=1.0, verified=True
            )
        }
    )
    assert compute_profile_hash(changed) != compute_profile_hash(real_profile)

    with _counting_writes(engine, "candidate") as counts:
        candidate_id = save_candidate_profile(session, changed)

    assert counts["n"] > 0, "a genuinely changed profile must still trigger a resync"
    candidate = session.get(Candidate, candidate_id)
    assert candidate.current_location == "A Different City"
    assert candidate.profile_fingerprint == compute_profile_hash(changed)


def test_candidate_data_correct_after_resync(real_profile, session):
    save_candidate_profile(session, real_profile)

    changed = real_profile.model_copy(
        update={
            "skills": tuple(real_profile.skills[:-1])  # drop one skill
        }
    )
    candidate_id = save_candidate_profile(session, changed)

    assert (
        session.query(Skill).filter_by(candidate_id=candidate_id).count()
        == len(changed.skills)
        == len(real_profile.skills) - 1
    )
    # No duplicate candidate rows were created for the resync.
    assert session.query(Candidate).count() == 1


def test_null_fingerprint_is_never_treated_as_a_match(real_profile, session, engine):
    """A pre-migration row (profile_fingerprint IS NULL) must always
    resync once, never be silently treated as already up to date."""
    candidate_id = save_candidate_profile(session, real_profile)
    candidate = session.get(Candidate, candidate_id)
    candidate.profile_fingerprint = None
    session.commit()

    with _counting_writes(engine, "candidate") as counts:
        save_candidate_profile(session, real_profile)

    assert counts["n"] > 0, "a NULL fingerprint must always trigger a resync, never a no-op"

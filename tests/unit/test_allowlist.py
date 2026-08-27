"""Phase 6C — `job_agent.applications.allowlist` unit tests.

Covers validity computation (expired/revoked excluded, exact
job_fingerprint+provider_name match required), and robustness against
SQLite's loss of timezone info on a DB round trip. `canonical_url` is
deliberately NOT checked by `get_active_allowlist_entry` itself — that
comparison is the caller's (`job_agent.applications.service.
submit_application`'s) responsibility, covered in
`tests/unit/test_applications_service.py`.
"""

from __future__ import annotations

import pytest

from job_agent.applications.allowlist import (
    create_allowlist_entry,
    get_active_allowlist_entry,
    revoke_allowlist_entry,
)
from job_agent.db.session import get_engine, get_session_factory, init_db


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


def test_freshly_created_entry_is_active(db_session):
    entry = create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1")
    db_session.commit()

    found = get_active_allowlist_entry(db_session, "fp-job", "structured_ats")
    assert found is not None
    assert found.id == entry.id
    assert found.canonical_url == "https://x.test/1"


def test_entry_for_wrong_job_fingerprint_is_not_found(db_session):
    create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1")
    db_session.commit()

    assert get_active_allowlist_entry(db_session, "OTHER", "structured_ats") is None


def test_entry_for_wrong_provider_name_is_not_found(db_session):
    create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1")
    db_session.commit()

    assert get_active_allowlist_entry(db_session, "fp-job", "some_other_provider") is None


def test_expired_entry_is_not_active(db_session):
    create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1", ttl_days=-1)
    db_session.commit()

    assert get_active_allowlist_entry(db_session, "fp-job", "structured_ats") is None


def test_expired_entry_is_not_active_after_a_db_round_trip(db_session):
    """Regression test: SQLite loses tzinfo on round trip — the expiry
    comparison must normalize a naive `expires_at` back to UTC rather
    than raising or comparing incorrectly."""
    entry = create_allowlist_entry(
        db_session, "fp-job", "structured_ats", "https://x.test/1", ttl_days=-1
    )
    db_session.commit()
    db_session.expire(entry)

    assert get_active_allowlist_entry(db_session, "fp-job", "structured_ats") is None


def test_revoked_entry_is_not_active(db_session):
    entry = create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1")
    db_session.commit()
    revoke_allowlist_entry(db_session, entry)
    db_session.commit()

    assert get_active_allowlist_entry(db_session, "fp-job", "structured_ats") is None


def test_most_recent_active_entry_is_returned(db_session):
    create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1")
    second = create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/2")
    db_session.commit()

    found = get_active_allowlist_entry(db_session, "fp-job", "structured_ats")
    assert found is not None
    assert found.id == second.id
    assert found.canonical_url == "https://x.test/2"


def test_revoking_the_newest_entry_falls_back_to_an_older_still_active_one(db_session):
    first = create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/1")
    second = create_allowlist_entry(db_session, "fp-job", "structured_ats", "https://x.test/2")
    db_session.commit()
    revoke_allowlist_entry(db_session, second)
    db_session.commit()

    found = get_active_allowlist_entry(db_session, "fp-job", "structured_ats")
    assert found is not None
    assert found.id == first.id


def test_entries_for_different_providers_on_the_same_job_are_independent(db_session):
    create_allowlist_entry(db_session, "fp-job", "provider_a", "https://x.test/1")
    entry_b = create_allowlist_entry(db_session, "fp-job", "provider_b", "https://x.test/1")
    db_session.commit()

    found_a = get_active_allowlist_entry(db_session, "fp-job", "provider_a")
    found_b = get_active_allowlist_entry(db_session, "fp-job", "provider_b")
    assert found_a is not None and found_a.provider_name == "provider_a"
    assert found_b is not None and found_b.id == entry_b.id

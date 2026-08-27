from __future__ import annotations

import pytest

from job_agent.applications.schema import ApplicationStatus
from job_agent.applications.state_machine import (
    IllegalStateTransitionError,
    can_transition,
    is_terminal,
    validate_transition,
)

S = ApplicationStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.DISCOVERED, S.MATCHED),
        (S.DISCOVERED, S.HUMAN_REQUIRED),
        (S.DISCOVERED, S.SKIPPED),
        (S.MATCHED, S.PREPARED),
        (S.MATCHED, S.HUMAN_REQUIRED),
        (S.HUMAN_REQUIRED, S.PREPARED),
        (S.HUMAN_REQUIRED, S.HUMAN_REQUIRED),
        (S.PREPARED, S.SUBMITTED),
        (S.PREPARED, S.SUBMISSION_UNCERTAIN),
        (S.SUBMITTED, S.VERIFIED),
        (S.SUBMITTED, S.FAILED),
        (S.SUBMISSION_UNCERTAIN, S.VERIFIED),
        (S.SUBMISSION_UNCERTAIN, S.FAILED),
        (S.SUBMISSION_UNCERTAIN, S.HUMAN_REQUIRED),
        (S.FAILED, S.MATCHED),
    ],
)
def test_legal_transitions_allowed(current, target):
    assert can_transition(current, target) is True
    validate_transition(current, target)  # must not raise


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.DISCOVERED, S.PREPARED),
        (S.DISCOVERED, S.SUBMITTED),
        (S.DISCOVERED, S.VERIFIED),
        (S.MATCHED, S.SUBMITTED),
        (S.MATCHED, S.VERIFIED),
        (S.PREPARED, S.VERIFIED),
        (S.PREPARED, S.MATCHED),
        (S.SUBMITTED, S.PREPARED),
        (S.SUBMITTED, S.MATCHED),
        (S.VERIFIED, S.SUBMITTED),
        (S.VERIFIED, S.PREPARED),
        (S.VERIFIED, S.FAILED),
        (S.SKIPPED, S.MATCHED),
        (S.SKIPPED, S.PREPARED),
        (S.FAILED, S.SUBMITTED),
        (S.FAILED, S.VERIFIED),
        (S.FAILED, S.PREPARED),
        # Phase 6A: SUBMISSION_UNCERTAIN must never be blindly retried —
        # these are the exact forbidden edges named in the Phase 6A spec.
        (S.SUBMISSION_UNCERTAIN, S.PREPARED),
        (S.SUBMISSION_UNCERTAIN, S.SUBMITTED),
        (S.SUBMISSION_UNCERTAIN, S.SUBMISSION_UNCERTAIN),
        (S.SUBMITTED, S.PREPARED),
        (S.SUBMITTED, S.SUBMITTED),
        (S.SUBMITTED, S.SUBMISSION_UNCERTAIN),
    ],
)
def test_illegal_transitions_rejected(current, target):
    assert can_transition(current, target) is False
    with pytest.raises(IllegalStateTransitionError):
        validate_transition(current, target)


def test_verified_and_skipped_are_terminal():
    assert is_terminal(S.VERIFIED) is True
    assert is_terminal(S.SKIPPED) is True


def test_failed_is_not_terminal_because_retries_must_be_possible():
    """Application is unique per (job_id, candidate_id) — if FAILED had no
    way out, a transient failure would permanently block ever applying to
    that job again, with no way to create a fresh row either."""
    assert is_terminal(S.FAILED) is False
    assert can_transition(S.FAILED, S.MATCHED) is True


def test_human_required_self_transition_allowed_for_idempotent_re_preparation():
    """Re-running prepare_application on an application already stuck at
    HUMAN_REQUIRED (the candidate hasn't answered the pending questions
    yet) must be a safe, idempotent re-audit — not an illegal jump that
    crashes the caller."""
    assert can_transition(S.HUMAN_REQUIRED, S.HUMAN_REQUIRED) is True
    validate_transition(S.HUMAN_REQUIRED, S.HUMAN_REQUIRED)  # must not raise


def test_no_transition_is_legal_from_a_terminal_state():
    for target in S:
        assert can_transition(S.VERIFIED, target) is False
        assert can_transition(S.SKIPPED, target) is False


def test_submission_uncertain_is_not_terminal_but_has_no_blind_retry_path():
    """SUBMISSION_UNCERTAIN (Phase 6A) has outgoing edges (VERIFIED,
    FAILED, HUMAN_REQUIRED) so it isn't terminal — but none of them is a
    path back to PREPARED/SUBMITTED, so there is no way to silently
    re-attempt an ambiguous submission; it can only be resolved
    (verified/failed) or escalated to a human."""
    assert is_terminal(S.SUBMISSION_UNCERTAIN) is False
    reachable = {t for t in S if can_transition(S.SUBMISSION_UNCERTAIN, t)}
    assert reachable == {S.VERIFIED, S.FAILED, S.HUMAN_REQUIRED}


def test_illegal_transition_error_carries_states():
    with pytest.raises(IllegalStateTransitionError) as exc_info:
        validate_transition(S.MATCHED, S.VERIFIED)
    assert exc_info.value.current == S.MATCHED
    assert exc_info.value.target == S.VERIFIED

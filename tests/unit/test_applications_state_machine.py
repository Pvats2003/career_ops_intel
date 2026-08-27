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
        (S.PREPARED, S.SUBMITTED),
        (S.SUBMITTED, S.VERIFIED),
        (S.SUBMITTED, S.FAILED),
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


def test_no_transition_is_legal_from_a_terminal_state():
    for target in S:
        assert can_transition(S.VERIFIED, target) is False
        assert can_transition(S.SKIPPED, target) is False


def test_illegal_transition_error_carries_states():
    with pytest.raises(IllegalStateTransitionError) as exc_info:
        validate_transition(S.MATCHED, S.VERIFIED)
    assert exc_info.value.current == S.MATCHED
    assert exc_info.value.target == S.VERIFIED

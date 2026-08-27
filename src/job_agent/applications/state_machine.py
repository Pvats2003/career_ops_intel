"""The single source of truth for which Application state transitions are
legal — every status change in this codebase must go through `transition()`
rather than assigning `.status` directly, so it is structurally impossible
to (for example) jump an application straight to VERIFIED or resurrect a
FAILED one into SUBMITTED without going through MATCHED/PREPARED again.

This is the primary defense against "an application marked successful
incorrectly" — see the Phase 5 adversarial review notes in
`job_agent.applications.service`.
"""

from __future__ import annotations

from job_agent.applications.schema import ApplicationStatus

_S = ApplicationStatus

# Terminal states: nothing may transition out of these.
#
# VERIFIED and SKIPPED are genuinely terminal: a verified application is
# done, and a skip (duplicate, rate limit, SAVE/SKIP match decision) is a
# deliberate decision that isn't this state machine's place to reverse.
#
# FAILED is deliberately NOT terminal: `Application` is unique per
# (job_id, candidate_id) (see db/models.py), so if FAILED had no way out,
# a transient failure (a provider timeout, a momentary form error) would
# permanently block ever applying to that job again — a fresh row can
# never be created for the same pair. FAILED -> MATCHED lets
# `job_agent.applications.service.retry_application` re-run preparation
# from scratch on the SAME row (never a new one), so "retry" means
# "re-audited attempt on the one record for this job", not "silently
# reuse the failed attempt's stale answers" or "duplicate application".
_TERMINAL: frozenset[ApplicationStatus] = frozenset({_S.VERIFIED, _S.SKIPPED})

_ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    _S.DISCOVERED: frozenset({_S.MATCHED, _S.HUMAN_REQUIRED, _S.SKIPPED, _S.FAILED}),
    _S.MATCHED: frozenset({_S.PREPARED, _S.HUMAN_REQUIRED, _S.SKIPPED, _S.FAILED}),
    _S.HUMAN_REQUIRED: frozenset({_S.PREPARED, _S.SKIPPED, _S.FAILED}),
    _S.PREPARED: frozenset({_S.SUBMITTED, _S.HUMAN_REQUIRED, _S.SKIPPED, _S.FAILED}),
    _S.SUBMITTED: frozenset({_S.VERIFIED, _S.FAILED}),
    _S.VERIFIED: frozenset(),
    _S.FAILED: frozenset({_S.MATCHED}),
    _S.SKIPPED: frozenset(),
}


class IllegalStateTransitionError(ValueError):
    def __init__(self, current: ApplicationStatus, target: ApplicationStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"cannot transition application from {current} to {target}")


def is_terminal(status: ApplicationStatus) -> bool:
    return status in _TERMINAL


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_transition(current: ApplicationStatus, target: ApplicationStatus) -> None:
    """Raises `IllegalStateTransitionError` unless the move is explicitly
    allowed. Every caller that changes `Application.status` must call this
    first — see `job_agent.applications.repository.transition_status`."""
    if not can_transition(current, target):
        raise IllegalStateTransitionError(current, target)

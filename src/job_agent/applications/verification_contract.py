"""Verification-evidence contract — built as Phase 6C.5 (Credential Safety
& Verification Foundation) groundwork, now actually wired into
`verify_application` by Phase 6C (controlled real-world execution).

============================================================================
PHASE 6C.5 groundwork; PHASE 6C is the deliberate consumer.

This module's shape-only plausibility check (`validate_submission_evidence`)
was built one phase before it had a real caller — exactly the same
"abstraction before any real implementation" pattern this project uses
throughout. Phase 6C is that caller: `job_agent.applications.service.
verify_application` now additionally requires this check to pass, but
ONLY for a provider with `requires_persisted_approval = True` (i.e. only
`job_agent.applications.providers.real_structured_ats.
RealStructuredATSProvider` today) — every other provider
(`ManualReviewProvider`, `StructuredATSProvider`) is completely unaffected;
`verify_application`'s original two-condition check
(`verified=True` AND concrete evidence) still governs them exactly as
before this phase.
============================================================================
REAL CREDENTIALS: NONE — this module itself never reads or holds one.
REAL SUBMISSIONS: NONE — this module makes no submission of any kind.
REAL NETWORK SUBMISSION CALLS: NONE — this module makes no network call.
BROWSER AUTOMATION: NONE.
============================================================================

WHAT THIS IS: `validate_submission_evidence()` documents and enforces the
*shape* genuine `SubmissionEvidence` (`job_agent.applications.schema`) would
need to have for a future real provider — a stronger check than the
existing `SubmissionEvidence.has_concrete_evidence` property (which only
asks "is at least one field non-blank"). This adds minimal plausibility
checks: a confirmation id long enough to be a real identifier rather than a
placeholder, a confirmation url that is actually a well-formed http(s) URL.

WHAT THIS IS CRITICALLY NOT: **shape-validity is not proof that a
submission occurred.** A provider — buggy, misconfigured, or malicious —
could construct evidence that passes every check here for a submission
that never happened; this validator has no way to independently confirm
anything against the real platform, because it never talks to the network
at all. Establishing genuine provenance (did this evidence really come
from the platform, not just from the provider's own say-so) requires an
independent, out-of-band signal — e.g. a confirmation email, a separately
authenticated re-fetch of the application's status — which is exactly the
kind of real-provider capability explicitly out of scope for this phase.
Treat a "valid" result from this function as "well-formed enough to be
worth a human's attention," never as "confirmed genuine."

WHAT THIS IS NOT (2): this module changes `verify_application`'s behavior
for exactly one provider — `RealStructuredATSProvider`
(`requires_persisted_approval = True`) — and nothing else. For every other
provider, `verify_application` still requires only `result.verified is
True` AND `result.evidence is not None` AND `result.evidence.
has_concrete_evidence`, exactly as before Phase 6C. This module was never
retroactively made to govern any provider that doesn't explicitly opt in
via that flag.

`ManualReviewProvider` and `StructuredATSProvider` still never produce
evidence that reaches this validator in production — both unconditionally
refuse `submit()`. `RealStructuredATSProvider` is the first (and, in this
Stage 1 pass, still only-ever-exercised-with-synthetic-data) provider whose
evidence this validator actually gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from job_agent.applications.schema import SubmissionEvidence

# Below this length a confirmation id reads as a placeholder/test value
# ("1", "ok", "x") rather than anything resembling a real platform-issued
# identifier — a plausibility floor, not a guarantee of authenticity.
_MIN_CONFIRMATION_ID_LENGTH = 6


@dataclass(frozen=True)
class EvidenceValidation:
    """Result of a shape-only plausibility check — see module docstring
    for why `valid=True` is not proof a submission occurred."""

    valid: bool
    reasons: tuple[str, ...] = ()


def _is_well_formed_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_submission_evidence(evidence: SubmissionEvidence) -> EvidenceValidation:
    """Shape-only plausibility check for `SubmissionEvidence`.

    Rejects the same "nothing concrete" case
    `SubmissionEvidence.has_concrete_evidence` already rejects, plus two
    additional plausibility checks a fabricated/incomplete stub is likely
    to fail: an implausibly short confirmation id, and a confirmation url
    that isn't actually a well-formed http(s) URL. Passing every check
    here is necessary, but never sufficient, evidence of a genuine
    submission — see the module docstring.
    """
    reasons: list[str] = []

    if not evidence.has_concrete_evidence:
        reasons.append("no concrete evidence field is populated")

    confirmation_id = (evidence.confirmation_id or "").strip()
    if confirmation_id and len(confirmation_id) < _MIN_CONFIRMATION_ID_LENGTH:
        reasons.append(
            f"confirmation_id is implausibly short ({len(confirmation_id)} chars) "
            "to be a genuine platform-issued identifier"
        )

    confirmation_url = (evidence.confirmation_url or "").strip()
    if confirmation_url and not _is_well_formed_http_url(confirmation_url):
        reasons.append("confirmation_url is not a well-formed http(s) URL")

    return EvidenceValidation(valid=not reasons, reasons=tuple(reasons))

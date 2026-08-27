"""Wires `config/rules.yaml`'s declared safety rules into actual
enforcement — Phase 6A.

Before Phase 6A, `RulesConfig` (`job_agent.config.models`) was loaded and
strictly validated at startup, but nothing in the codebase ever read
`config.rules` — `stop_on_captcha`, `stop_on_mfa`, and
`stop_on_unexpected_form` were declared, not enforced. Phase 3's
deterministic matcher independently reimplements an overlapping set of
hard-stop reasons in code, but never consults this file. This module is
the first real reader of `config.rules.safety`, and it is the ONLY reader
of it for this purpose: there is no second, independent copy of these
flags anywhere else in the codebase — `AppConfig.rules` (already loaded
and validated by `job_agent.config.loader.load_config`) is the sole source
of truth this module consults.

Deliberately kept out of `job_agent.applications.provider`: a provider may
report raw structural facts via `ApplicationInspection` (CAPTCHA present?
MFA present? was the form structure recognized?), but it never decides
the HUMAN_REQUIRED consequence of those facts — that decision lives here,
in core code, applied by the calling service
(`job_agent.applications.service.handle_application_inspection`), never
by the provider itself. This is the same "provider reports, core decides"
boundary the Phase 6 recon's security review requires for submission
eligibility, extended here to inspection-driven human-required routing.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.applications.schema import ApplicationInspection
from job_agent.config.models import RulesConfig

CAPTCHA_DETECTED = "captcha_detected"
MFA_DETECTED = "mfa_detected"
CONSENT_REQUIRED = "consent_required"
UNEXPECTED_FORM_STRUCTURE = "unexpected_form_structure"


@dataclass(frozen=True)
class InspectionVerdict:
    """The single authoritative outcome of evaluating one
    `ApplicationInspection` against the real `config.rules.safety` flags.

    `reason`, when set, is always one of the module-level constants above
    — chosen to match `config/rules.yaml`'s own `hard_stop_conditions`
    vocabulary exactly, so an audit event's reason string is traceable
    straight back to the declared rule that produced it.
    """

    human_required: bool
    reason: str | None = None


def evaluate_inspection(rules: RulesConfig, inspection: ApplicationInspection) -> InspectionVerdict:
    """Maps a provider's raw structural facts to a HUMAN_REQUIRED verdict,
    driven entirely by the actual, loaded `config/rules.yaml` values.

    Checked in a fixed order (CAPTCHA, then MFA, then required consent,
    then unrecognized structure) so the audit reason is always the single
    most specific condition that applies, not an arbitrary one when more
    than one fact is true at once.
    """
    if inspection.captcha_detected and rules.safety.stop_on_captcha:
        return InspectionVerdict(human_required=True, reason=CAPTCHA_DETECTED)
    if inspection.mfa_detected and rules.safety.stop_on_mfa:
        return InspectionVerdict(human_required=True, reason=MFA_DETECTED)
    if inspection.consent_required and rules.safety.stop_on_consent_required:
        return InspectionVerdict(human_required=True, reason=CONSENT_REQUIRED)
    if not inspection.structure_recognized and rules.safety.stop_on_unexpected_form:
        return InspectionVerdict(human_required=True, reason=UNEXPECTED_FORM_STRUCTURE)
    return InspectionVerdict(human_required=False, reason=None)

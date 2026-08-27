"""Canonical types for the Job Application Engine — Phase 5, widened by
Phase 6A's provider-architecture contracts.

`ApplicationStatus` is the fixed, explicit state list this phase was built
around (not the larger set sketched in earlier BUILD PROMPT drafts):

    DISCOVERED -> MATCHED -> PREPARED -> SUBMITTED -> VERIFIED
         │            │           │           │
         ▼            ▼           ▼           ▼
    HUMAN_REQUIRED -> PREPARED   FAILED   SUBMISSION_UNCERTAIN -> VERIFIED
                                 SKIPPED                       -> FAILED
                                                                -> HUMAN_REQUIRED

`job_agent.applications.state_machine` is the single place that enforces
which of these transitions are legal — nothing here can jump straight from
MATCHED to VERIFIED, for instance. `SUBMISSION_UNCERTAIN` (added in Phase
6A) exists for exactly one failure mode: a submission attempt whose actual
outcome could not be determined (e.g. a network timeout after the request
may already have reached the platform) — the system must never guess
FAILED or VERIFIED for that case, so it has its own state with its own,
deliberately narrow set of legal exits. No `ApplicationProvider` shipped in
Phase 6A can ever produce this state; the transition exists so the
contract is ready when a real provider that can time out ambiguously is
eventually built (Phase 6B+).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class ApplicationStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    MATCHED = "MATCHED"
    PREPARED = "PREPARED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class QuestionCategory(StrEnum):
    """BUILD PROMPT section 14's application-question taxonomy."""

    PERSONAL = "PERSONAL"
    CONTACT = "CONTACT"
    EDUCATION = "EDUCATION"
    EXPERIENCE = "EXPERIENCE"
    TECHNICAL = "TECHNICAL"
    MOTIVATION = "MOTIVATION"
    COMPANY = "COMPANY"
    ROLE = "ROLE"
    SALARY = "SALARY"
    VISA = "VISA"
    LEGAL = "LEGAL"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    AVAILABILITY = "AVAILABILITY"
    RELOCATION = "RELOCATION"
    CUSTOM = "CUSTOM"


# Categories where an unverified/UNKNOWN candidate fact must never be
# guessed at — these always route to HUMAN_REQUIRED rather than attempting
# generation, regardless of LLM availability. See rules.yaml
# human_review_unknown and BUILD PROMPT section 14's own examples.
HARD_BLOCK_CATEGORIES = frozenset(
    {
        QuestionCategory.SALARY,
        QuestionCategory.VISA,
        QuestionCategory.LEGAL,
        QuestionCategory.DEMOGRAPHIC,
    }
)


class ApplicationQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    category: QuestionCategory
    required: bool = True


class GeneratedAnswer(BaseModel):
    """Mirrors BUILD PROMPT section 14's answer contract exactly:
    `answer` is None whenever `requires_human` is True — there is never a
    guessed value sitting alongside a human-review flag."""

    model_config = ConfigDict(frozen=True)

    question: str
    category: QuestionCategory
    answer: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    requires_human: bool
    validated: bool
    validation_notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _answer_matches_requires_human(self) -> GeneratedAnswer:
        if self.requires_human and self.answer is not None:
            raise ValueError("requires_human=True must never carry a guessed answer value")
        if not self.requires_human and self.answer is None:
            raise ValueError("requires_human=False requires an actual answer value")
        return self


class SubmissionEvidence(BaseModel):
    """What a provider must produce for a submission to be trusted at all.

    At least one concrete, checkable field is required — see the
    validator below. This is what `verify_application` demands before any
    transition to SUBMITTED/VERIFIED is allowed; see
    `job_agent.applications.service`.
    """

    model_config = ConfigDict(frozen=True)

    confirmation_id: str | None = None
    confirmation_url: str | None = None
    confirmation_text: str | None = None
    screenshot_path: str | None = None
    submitted_at: datetime = Field(default_factory=utcnow)

    @property
    def has_concrete_evidence(self) -> bool:
        """True only if at least one field carries real, non-blank content —
        a provider returning whitespace (`" "`) must not count as evidence
        just because the field is technically non-None."""
        return any(
            value is not None and value.strip() != ""
            for value in (
                self.confirmation_id, self.confirmation_url,
                self.confirmation_text, self.screenshot_path,
            )
        )


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verified: bool
    evidence: SubmissionEvidence | None
    reason: str


# --------------------------------------------------------------------------
# Phase 6A — provider-architecture contract types.
#
# These describe what a *future*, real `ApplicationProvider` would report
# about a live platform. No Phase 6A provider populates them from a real
# platform — `ManualReviewProvider` returns honest, conservative defaults
# for all three (see job_agent.applications.provider) — but the shape is
# fixed now so the core engine, the safety-rule enforcement in
# job_agent.applications.rules_enforcement, and every test written against
# them do not need to change again when a real provider is eventually
# built.
# --------------------------------------------------------------------------
class ApplicationTarget(BaseModel):
    """Confirms (or fails to confirm) that a provider-specific application
    endpoint exists for one job — nothing more. Carries no candidate data
    and no credential of any kind; `provider_reference` is an opaque
    handle a real provider could use to re-identify the same target on a
    later call (e.g. a form ID), never a secret."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    reachable: bool
    provider_reference: str | None = None
    detail: str = ""


class ApplicationInspection(BaseModel):
    """Raw structural facts a provider observed about an application
    target — CAPTCHA/MFA/consent presence, whether the form structure was
    recognized. Deliberately **not** a HUMAN_REQUIRED decision: a provider
    reports facts, it never decides eligibility. That decision is made
    exactly once, in `job_agent.applications.rules_enforcement.
    evaluate_inspection`, by consulting the real `config/rules.yaml`
    values — never duplicated or reimplemented by a provider."""

    model_config = ConfigDict(frozen=True)

    structure_recognized: bool
    captcha_detected: bool = False
    mfa_detected: bool = False
    consent_required: bool = False
    detail: str = ""


class PreparedFormState(BaseModel):
    """An opaque handle representing 'answers have been staged against a
    target form but nothing has been transmitted yet' — deliberately
    inert beyond that fact, so that *filling* a form and *submitting* it
    remain two separately-audited actions (BUILD PROMPT Phase 6 recon,
    STEP 2: preparation vs. execution vs. verification). No Phase 6A
    provider actually stages anything on a real platform."""

    model_config = ConfigDict(frozen=True)

    target_job_id: int
    answer_count: int
    provider_reference: str | None = None
    detail: str = ""

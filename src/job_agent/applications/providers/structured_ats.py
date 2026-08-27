"""StructuredATSProvider — the first concrete structured-ATS provider adapter
built on the Phase 6A `ApplicationProvider` architecture (Phase 6B).

WHAT THIS IS: a demonstration that the Phase 6A provider architecture works
against a realistic structured-ATS form model — job/application URL,
provider-specific application identifier, a list of typed fields (text,
textarea, select, checkbox, radio, yes/no, numeric, date), required/optional
flags, and CAPTCHA/MFA/consent presence — while remaining completely
submission-disabled.

WHAT THIS IS NOT: this provider is an adapter, nothing more. It never
decides whether an application is allowed, candidate eligibility,
submission approval, automation level, safety gates, verification outcome,
or duplicate policy — those remain the exclusive responsibility of
`job_agent.applications.service`, `job_agent.applications.state_machine`,
`job_agent.applications.rules_enforcement`, `job_agent.applications.
duplicates`, and `job_agent.applications.rate_limits`. This module never
imports any of them (enforced by
`test_structured_ats_provider.test_provider_module_never_imports_core_decision_logic`,
mirroring Phase 6A's identical test for `job_agent.applications.provider`).

LOCAL-FIXTURE-ONLY BY CONSTRUCTION: a `StructuredATSProvider` is
constructed with a plain, in-memory mapping of `job_id -> ATSApplicationForm`
supplied by the caller (fake/local data or a controlled test fixture, per
the Phase 6B spec). There is no HTTP client, no network import, and no
platform credential anywhere in this module — "no real submission network
call" and "no browser automation" hold by construction, not by a runtime
guard that could be bypassed. See `test_no_network_imports_in_this_module`.

SUBMISSION BOUNDARY: `submit()` unconditionally raises
`SubmissionRefusedError`, exactly like `ManualReviewProvider`. There is no
configuration flag, no code path, and no set of constructor arguments that
can make it do anything else — this is Phase 6B STEP 3's "no hidden path
such as dry_run=false -> provider.submit()" requirement satisfied
structurally rather than by a guard that could later be removed.
`verify()` unconditionally reports `verified=False, evidence=None` — even
when handed evidence with a populated `confirmation_id` — because nothing
was ever actually submitted for it to confirm (STEP 9).

UNTRUSTED CONTENT: every field's label, placeholder, description, and
option list is treated as untrusted external content, exactly like a real
ATS form would be. This module never branches on the *content* of any of
those strings — only on structural facts (`field_type` membership in the
supported set, `captcha_present`, `mfa_present`, `consent_required`, which
are plain booleans/enums the "platform" reports, analogous to an HTTP
status code rather than free text). Field text is carried, verbatim and
unexecuted, into the question representation and from there into the
existing, already-hardened answer-generation pipeline
(`job_agent.applications.answer_engine.classify_question`/
`generate_answer`), which independently delimits and instructs an LLM (if
any) never to follow directives embedded in question text. See
`test_structured_ats_provider.py`'s prompt-injection fixtures for the exact
adversarial strings this is verified against.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from job_agent.applications.errors import SubmissionRefusedError
from job_agent.applications.provider import ApplicationProvider, ProviderHealthCheck
from job_agent.applications.schema import (
    ApplicationInspection,
    ApplicationQuestion,
    ApplicationTarget,
    GeneratedAnswer,
    PreparedFormState,
    QuestionCategory,
    SubmissionEvidence,
    VerificationResult,
)
from job_agent.db.models import Job as JobRow


class ATSFieldType(StrEnum):
    """Field types this provider knows how to structurally recognize.

    A field reporting any other `field_type` string (an unsupported/
    unrecognized type from the "platform"'s point of view) is exactly what
    drives `structure_recognized=False` in `inspect_application` — see
    `_structure_recognized` below.
    """

    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    SELECT = "SELECT"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"
    YES_NO = "YES_NO"
    NUMERIC = "NUMERIC"
    DATE = "DATE"


_SUPPORTED_FIELD_TYPES = frozenset(t.value for t in ATSFieldType)

# Representative fallback used only when no fixture form is registered for
# a job — mirrors ManualReviewProvider's own representative set (Phase 5)
# so a job without a fixture still degrades to honest, exercisable
# behavior rather than an empty question list. Deliberately a separate,
# small tuple rather than importing ManualReviewProvider's private
# `_STANDARD_QUESTIONS` constant across module boundaries.
_FALLBACK_QUESTIONS: tuple[ApplicationQuestion, ...] = (
    ApplicationQuestion(text="Tell me about yourself.", category=QuestionCategory.MOTIVATION),
    ApplicationQuestion(text="Why do you want to work here?", category=QuestionCategory.COMPANY),
    ApplicationQuestion(
        text="Why are you a good fit for this role?", category=QuestionCategory.ROLE
    ),
    ApplicationQuestion(
        text="Will you now or in the future require visa sponsorship?",
        category=QuestionCategory.VISA,
    ),
    ApplicationQuestion(
        text="What are your salary expectations?", category=QuestionCategory.SALARY
    ),
    ApplicationQuestion(
        text="When are you available to start?", category=QuestionCategory.AVAILABILITY
    ),
)


class ATSFormField(BaseModel):
    """One field of a structured ATS application form.

    `label`, `placeholder`, `description`, and `options` are UNTRUSTED
    EXTERNAL CONTENT — this provider never interprets them as instructions,
    only ever carries them as inert text (see module docstring).
    `field_type` is a plain string, not `ATSFieldType`, deliberately: a real
    platform can report a type this provider doesn't recognize, and that
    must be representable (it drives the `unsupported_field_type` ->
    unrecognized-structure path), not rejected at parse time.
    """

    model_config = ConfigDict(frozen=True)

    field_id: str
    label: str
    field_type: str
    required: bool = True
    options: tuple[str, ...] = Field(default_factory=tuple)
    placeholder: str = ""
    description: str = ""


class ATSApplicationForm(BaseModel):
    """A local/fixture representation of one structured-ATS application —
    never fetched over the network by this provider. The caller (a test, a
    future orchestrator wiring in real fixtures) is entirely responsible
    for how this data was obtained."""

    model_config = ConfigDict(frozen=True)

    ats_application_url: str
    ats_application_id: str
    captcha_present: bool = False
    mfa_present: bool = False
    consent_required: bool = False
    fields: tuple[ATSFormField, ...] = Field(default_factory=tuple)


def _structure_recognized(form: ATSApplicationForm) -> bool:
    """A form's structure counts as recognized only if it has at least one
    field and every field's reported type is one this provider actually
    understands. An empty field list or any unsupported field type both
    yield `False` — deliberately conservative, matching the ABC default's
    posture of never claiming recognition it hasn't earned."""
    if not form.fields:
        return False
    return all(field.field_type in _SUPPORTED_FIELD_TYPES for field in form.fields)


def _question_text(field: ATSFormField) -> str:
    """Builds the plain-text question representation handed to
    `classify_question`/`generate_answer`. Every untrusted string the field
    carries (label, placeholder, description, options) is concatenated as
    inert data — none of it is parsed, evaluated, or treated as a
    directive; the existing answer-engine's untrusted-content handling
    (delimiting + explicit system-prompt instruction not to follow embedded
    directives) then applies to the whole string exactly as it would to any
    other question text."""
    parts = [field.label]
    if field.placeholder:
        parts.append(f"(placeholder: {field.placeholder})")
    if field.description:
        parts.append(f"(description: {field.description})")
    if field.options:
        parts.append(f"(options: {', '.join(field.options)})")
    return " ".join(parts)


def _to_question(field: ATSFormField) -> ApplicationQuestion:
    from job_agent.applications.answer_engine import classify_question

    text = _question_text(field)
    return ApplicationQuestion(
        text=text, category=classify_question(text), required=field.required
    )


class StructuredATSProvider(ApplicationProvider):
    """First concrete structured-ATS provider adapter (Phase 6B).

    Constructed with a plain, caller-supplied mapping of
    `job_id -> ATSApplicationForm` — local/fixture data only, never fetched
    from a network. This provider reports structural facts (reachability,
    CAPTCHA/MFA/consent presence, recognized-or-not field types) and
    converts fields into `ApplicationQuestion`s for the existing answer
    engine; it never decides what those facts mean for application state —
    see the module docstring's "provider reports facts, core decides
    consequences" boundary, inherited unchanged from Phase 6A.
    """

    name = "structured_ats"

    def __init__(self, forms: Mapping[int, ATSApplicationForm]) -> None:
        self._forms: dict[int, ATSApplicationForm] = dict(forms)

    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        form = self._forms.get(job.id)
        if form is None:
            return list(_FALLBACK_QUESTIONS)
        return [_to_question(field) for field in form.fields]

    def submit(self, job: JobRow, answers: list[GeneratedAnswer]) -> SubmissionEvidence:
        # Unconditional refusal — no branch, no flag, no answers-dependent
        # path reaches anything resembling a real submission. See module
        # docstring's SUBMISSION BOUNDARY section.
        raise SubmissionRefusedError(
            f"StructuredATSProvider has no real submission capability for job {job.id} "
            f"({job.company_name} — {job.title}). Submission is an explicit unsupported "
            "capability in this phase; a human must submit this application manually."
        )

    def verify(self, job: JobRow, evidence: SubmissionEvidence) -> VerificationResult:
        # Deliberately ignores whatever `evidence` contains — even a
        # populated confirmation_id must never be trusted, because nothing
        # was ever actually submitted through this provider to produce
        # genuine evidence. See STEP 9 / module docstring.
        return VerificationResult(
            verified=False,
            evidence=None,
            reason=(
                "StructuredATSProvider has no real submission integration; nothing was "
                "ever actually submitted, so no evidence can be verified."
            ),
        )

    def health_check(self) -> ProviderHealthCheck:
        return ProviderHealthCheck(
            healthy=True,
            detail=(
                f"structured_ats: {len(self._forms)} local fixture form(s) registered, "
                "no external dependency"
            ),
            checked_at=datetime.now(UTC),
        )

    def discover_application(self, job: JobRow) -> ApplicationTarget:
        form = self._forms.get(job.id)
        if form is None:
            return ApplicationTarget(
                job_id=job.id,
                reachable=False,
                detail=f"no structured-ATS fixture form registered for job {job.id}",
            )
        return ApplicationTarget(
            job_id=job.id,
            reachable=True,
            provider_reference=form.ats_application_id,
            detail=f"structured-ATS fixture form found for job {job.id}",
        )

    def inspect_application(
        self, job: JobRow, target: ApplicationTarget
    ) -> ApplicationInspection:
        form = self._forms.get(job.id)
        if form is None or not target.reachable:
            return ApplicationInspection(
                structure_recognized=False,
                detail="no discovered structured-ATS target to inspect",
            )
        return ApplicationInspection(
            structure_recognized=_structure_recognized(form),
            captcha_detected=form.captcha_present,
            mfa_detected=form.mfa_present,
            consent_required=form.consent_required,
            detail=f"inspected {len(form.fields)} field(s) on the local fixture form",
        )

    def fill_application(
        self, job: JobRow, target: ApplicationTarget, answers: list[GeneratedAnswer]
    ) -> PreparedFormState:
        # Stages a count only — never calls submit(), never transmits
        # anything. Mirrors the ABC default but with an honest,
        # provider-identified detail message.
        form = self._forms.get(job.id)
        return PreparedFormState(
            target_job_id=job.id,
            answer_count=len(answers),
            provider_reference=form.ats_application_id if form else None,
            detail=(
                "StructuredATSProvider stages answers locally only — a human must submit "
                "this application manually; nothing was transmitted."
            ),
        )

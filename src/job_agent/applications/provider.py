"""ApplicationProvider plugin interface — the application-side counterpart
to `job_agent.jobs.source.JobSource`.

Exactly like Phase 2's job sources, the core application engine
(`job_agent.applications.service`) is written against this interface, not
against any specific job platform — adding a real ATS integration later
means implementing `ApplicationProvider`, not touching the state machine,
the answer engine, or the safety gates.

There is exactly one concrete implementation shipped in production code:
`ManualReviewProvider`, whose `submit()` always refuses. This is
deliberate, not a placeholder to "finish later" — BUILD PROMPT's own Phase
5/6 split reserves real browser-automation/ATS integrations for a later
phase, and the task at hand explicitly forbids real external submissions
during this work. A permissive fake provider exists only in the test
suite, never in `src/`.

Phase 6A widens this interface with four additional, **concrete** (not
abstract) methods — `discover_application`, `inspect_application`,
`retrieve_application_questions`, `fill_application` — covering
application-*preparation* concerns the recon identified as missing:
confirming a target exists, reporting structural facts (CAPTCHA/MFA/
consent/unrecognized-form), and staging (never transmitting) answers. They
are concrete, not abstract, specifically so every existing provider
(`ManualReviewProvider`, and every fake provider in the test suite) keeps
instantiating and passing unchanged — the safe base-class defaults are
conservative (`reachable=False`, `structure_recognized=False`), never
optimistic, so a provider that doesn't override them is treated as "not
actually inspected" rather than "confirmed safe."

Architectural boundary (Phase 6A security review): a provider reports
facts, it never decides consequences. `inspect_application`'s result
feeds `job_agent.applications.rules_enforcement.evaluate_inspection`,
which is the ONLY place a HUMAN_REQUIRED-from-inspection decision is made,
using the real `config/rules.yaml` values — never a provider, and never a
second copy of those rules. `submit`/`verify` (unchanged from Phase 5)
remain the only methods that can produce `SubmissionEvidence`/
`VerificationResult`; nothing added in Phase 6A grants a provider any new
way to reach SUBMITTED/VERIFIED or to influence `config.is_submission_
allowed()`, automation-level, or rate-limit decisions — those stay entirely
in `job_agent.applications.service`, which no `ApplicationProvider`
implementation may import.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from job_agent.applications.errors import SubmissionRefusedError
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


@dataclass(frozen=True)
class ProviderHealthCheck:
    healthy: bool
    detail: str
    checked_at: datetime


class ApplicationProvider(ABC):
    name: str

    # ------------------------------------------------------------------
    # Capability flag (Phase 6B inspection wiring). Defaults to `False` so
    # every existing provider — `ManualReviewProvider`, every fake
    # provider in the test suite, anything written against the Phase 5/6A
    # interface before this flag existed — is treated as "does not
    # perform real inspection" without any code change on its part.
    #
    # This exists because `inspect_application`'s ABC default reports
    # `structure_recognized=False` (a conservative "not actually
    # inspected", never an optimistic guess) — which is exactly correct
    # for a provider that never overrides it, but is also exactly the
    # signal `rules_enforcement.evaluate_inspection` uses to route to
    # HUMAN_REQUIRED via `unexpected_form_structure`. If
    # `job_agent.applications.service.prepare_application` called
    # `inspect_application` unconditionally for every provider, every
    # existing provider that has never implemented real inspection would
    # suddenly route every application to HUMAN_REQUIRED — a correctness
    # regression, not a safety improvement (see Phase 6A's own README:
    # this exact risk was flagged and deliberately deferred). A provider
    # must explicitly opt in by setting `supports_inspection = True` once
    # it has implemented `discover_application`/`inspect_application`
    # with genuine structural-fact detection.
    #
    # Opting in is purely a capability declaration — it grants no new
    # authority. `inspect_application`'s result still only ever reaches
    # `job_agent.applications.rules_enforcement.evaluate_inspection`,
    # which is still the only place a HUMAN_REQUIRED-from-inspection
    # decision is made; the provider decides nothing.
    # ------------------------------------------------------------------
    supports_inspection: bool = False

    # ------------------------------------------------------------------
    # Capability flag (Phase 6C — controlled real-world execution).
    # Defaults to `False` so every existing provider — `ManualReviewProvider`,
    # `StructuredATSProvider`, every fake provider in the test suite — is
    # completely unaffected and keeps using the original Phase 5 submission
    # gate in `job_agent.applications.service.submit_application` (automation
    # level 4 OR an explicit `human_approved=True` argument). That original
    # gate remains exactly as it was — `applications run` is untouched.
    #
    # A provider that sets this `True` is instead gated by the STRICTER
    # Phase 6C path: a valid, unexpired, unconsumed, fingerprint-matching
    # `ApplicationApproval` record is the ONLY way past the gate.
    # `config.automation.automation.level` is never even consulted for such
    # a provider — there is no automation level, including 4, that can
    # substitute for a real, persisted, human-created approval. This closes
    # the gap where `automation_level == 4` alone could satisfy the old
    # gate's `automation_level >= 4 OR human_approved` check regardless of
    # whether anyone had actually approved anything.
    #
    # Opting in is a capability declaration, not a grant of authority: it
    # only changes which gate `submit_application` enforces before ever
    # calling `provider.submit()` — the provider itself still decides
    # nothing about whether it gets called.
    # ------------------------------------------------------------------
    requires_persisted_approval: bool = False

    @abstractmethod
    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        """Return the questions this job's application requires answering.

        A real integration would parse the actual application form; until
        one exists, an implementation may return a representative fixed
        set — but must never claim to have read a real form it hasn't.
        """

    @abstractmethod
    def submit(self, job: JobRow, answers: list[GeneratedAnswer]) -> SubmissionEvidence:
        """Attempt a real submission and return genuine evidence of it.

        Must raise `SubmissionRefusedError` (or another `ProviderError`)
        rather than return fabricated/placeholder evidence if it cannot
        actually submit — callers rely on this to keep FAILED distinct
        from a false SUBMITTED.
        """

    @abstractmethod
    def verify(self, job: JobRow, evidence: SubmissionEvidence) -> VerificationResult:
        """Independently confirm a prior submission actually went through."""

    @abstractmethod
    def health_check(self) -> ProviderHealthCheck: ...

    # ------------------------------------------------------------------
    # Phase 6A widened contract — concrete, safe-by-default. A real future
    # provider overrides these; no existing provider is forced to.
    # ------------------------------------------------------------------
    def discover_application(self, job: JobRow) -> ApplicationTarget:
        """Confirm a provider-specific application endpoint exists for
        this job, without creating any state on the provider's side and
        without touching any candidate data.

        Default: reports `reachable=False` rather than guessing — a
        provider must explicitly prove reachability to claim it.
        """
        return ApplicationTarget(
            job_id=job.id,
            reachable=False,
            detail="base ApplicationProvider performs no real target discovery",
        )

    def inspect_application(
        self, job: JobRow, target: ApplicationTarget
    ) -> ApplicationInspection:
        """Report raw structural facts about the target — CAPTCHA/MFA/
        consent presence, whether the form structure is recognized.
        **Never** a HUMAN_REQUIRED decision; see this module's docstring
        and `job_agent.applications.rules_enforcement`.

        Default: `structure_recognized=False`, which
        `rules_enforcement.evaluate_inspection` maps to HUMAN_REQUIRED
        whenever `config.rules.safety.stop_on_unexpected_form` is enabled
        (the safe default) — a real provider must explicitly earn
        `structure_recognized=True`.
        """
        return ApplicationInspection(
            structure_recognized=False,
            detail="base ApplicationProvider performs no real structural inspection",
        )

    def retrieve_application_questions(
        self, job: JobRow, target: ApplicationTarget
    ) -> list[ApplicationQuestion]:
        """Phase 6A name for real per-target form-scraping. Default
        delegates to `get_questions()` so Phase 5 behavior is unchanged
        until a real provider overrides this with genuine form-reading."""
        return self.get_questions(job)

    def fill_application(
        self, job: JobRow, target: ApplicationTarget, answers: list[GeneratedAnswer]
    ) -> PreparedFormState:
        """Stage already-validated answers against the target form.
        **Must never transmit anything** — that is `submit()`'s job, and
        only `submit()`'s. Separating fill from submit means "the form is
        filled" and "the form was sent" stay two distinct, distinctly
        audited events even once a real provider exists.

        Default: returns an inert handle describing nothing was actually
        staged anywhere.
        """
        return PreparedFormState(
            target_job_id=job.id,
            answer_count=len(answers),
            detail="base ApplicationProvider performs no real form-filling",
        )


# A small, representative question set standing in for real form-scraping,
# chosen to exercise every hard-block category (BUILD PROMPT section 14)
# plus a couple of ordinarily-answerable ones.
_STANDARD_QUESTIONS: tuple[ApplicationQuestion, ...] = (
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


class ManualReviewProvider(ApplicationProvider):
    """The only production ApplicationProvider in Phase 5/6A.

    Represents "no real ATS integration exists" honestly: it can surface a
    representative question set so the rest of the pipeline (answer
    generation, validation, human-review routing) is fully exercisable and
    testable, but it never submits anything anywhere, and it never
    fabricates verification evidence for a submission it didn't make.

    Overrides every Phase 6A method explicitly (rather than relying
    silently on the ABC's generic defaults) so its own honesty about
    having no real platform integration is visible in each method, not
    just inherited.
    """

    name = "manual_review"
    # Explicit, not just inherited — never claims real inspection since it
    # never performs any (its inspect_application below always reports
    # structure_recognized=False honestly, but without this flag set to
    # False the *caller* has no reliable way to distinguish "a real
    # provider inspected this and found it unrecognized" from "this
    # provider never inspects anything at all").
    supports_inspection = False
    # Explicit, not just inherited — ManualReviewProvider stays on the
    # original Phase 5 gate (automation level 4 OR human_approved=True);
    # it never persists or requires an ApplicationApproval record.
    requires_persisted_approval = False

    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        return list(_STANDARD_QUESTIONS)

    def submit(self, job: JobRow, answers: list[GeneratedAnswer]) -> SubmissionEvidence:
        raise SubmissionRefusedError(
            f"No real application-submission integration exists for job {job.id} "
            f"({job.company_name} — {job.title}). This job requires a human to submit "
            "the application manually."
        )

    def verify(self, job: JobRow, evidence: SubmissionEvidence) -> VerificationResult:
        return VerificationResult(
            verified=False,
            evidence=None,
            reason="ManualReviewProvider never submits anything, so there is nothing to verify.",
        )

    def health_check(self) -> ProviderHealthCheck:
        return ProviderHealthCheck(
            healthy=True, detail="manual review only, no external dependency",
            checked_at=datetime.now(UTC),
        )

    def discover_application(self, job: JobRow) -> ApplicationTarget:
        return ApplicationTarget(
            job_id=job.id,
            reachable=False,
            detail=(
                f"ManualReviewProvider performs no real target discovery for job {job.id} "
                f"({job.company_name} — {job.title})."
            ),
        )

    def inspect_application(
        self, job: JobRow, target: ApplicationTarget
    ) -> ApplicationInspection:
        return ApplicationInspection(
            structure_recognized=False,
            detail="ManualReviewProvider performs no real structural inspection.",
        )

    def retrieve_application_questions(
        self, job: JobRow, target: ApplicationTarget
    ) -> list[ApplicationQuestion]:
        return self.get_questions(job)

    def fill_application(
        self, job: JobRow, target: ApplicationTarget, answers: list[GeneratedAnswer]
    ) -> PreparedFormState:
        return PreparedFormState(
            target_job_id=job.id,
            answer_count=len(answers),
            detail=(
                "ManualReviewProvider performs no real form-filling — a human must fill "
                "and submit this application manually."
            ),
        )

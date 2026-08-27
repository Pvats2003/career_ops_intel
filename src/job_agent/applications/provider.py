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
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from job_agent.applications.errors import SubmissionRefusedError
from job_agent.applications.schema import (
    ApplicationQuestion,
    GeneratedAnswer,
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
    """The only production ApplicationProvider in Phase 5.

    Represents "no real ATS integration exists" honestly: it can surface a
    representative question set so the rest of the pipeline (answer
    generation, validation, human-review routing) is fully exercisable and
    testable, but it never submits anything anywhere, and it never
    fabricates verification evidence for a submission it didn't make.
    """

    name = "manual_review"

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

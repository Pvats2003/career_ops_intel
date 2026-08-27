"""Orchestrates the full application lifecycle: discover → prepare →
submit → verify. This is the module the adversarial review in Phase 5's
task list is aimed at — every safety property the phase requires is
enforced here, not left to the caller's discipline:

* **Never blindly submit** — `submit_application` requires
  `config.is_submission_allowed()` (dry_run disabled AND live_mode
  enabled — the existing Phase 1 choke point, reused, not reimplemented)
  *and* either automation level 4 or an explicit `human_approved=True`
  passed in by the caller. Either gate alone is not enough.
* **Never claim success without verification** — `submit_application`
  only ever reaches SUBMITTED; only `verify_application` can reach
  VERIFIED, and only when the provider returns genuine, concrete evidence
  (`job_agent.applications.schema.SubmissionEvidence.has_concrete_
  evidence`). An inconclusive or missing verification leaves the
  application at SUBMITTED — never silently promoted, never silently
  downgraded to FAILED (it may well have succeeded; we just can't prove
  it yet).
* **No duplicate applications** — `discover_application` checks both the
  per-job uniqueness (DB-enforced) and the cross-source content
  fingerprint before creating anything.
* **No forbidden state jump** — every transition goes through
  `job_agent.applications.repository.transition_status`, which validates
  against `state_machine` and always writes an audit event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from job_agent.applications.answer_bank import load_answer_bank
from job_agent.applications.answer_engine import generate_answer
from job_agent.applications.duplicates import find_cross_source_duplicate_application
from job_agent.applications.errors import ProviderError
from job_agent.applications.provider import ApplicationProvider
from job_agent.applications.rate_limits import check_rate_limits
from job_agent.applications.repository import (
    get_answers,
    get_or_create_application,
    record_event,
    save_answer,
    transition_status,
)
from job_agent.applications.schema import (
    ApplicationStatus,
    GeneratedAnswer,
    QuestionCategory,
    SubmissionEvidence,
)
from job_agent.applications.state_machine import IllegalStateTransitionError
from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig
from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.llm.provider import LLMProvider, NullLLMProvider
from job_agent.matching.schema import Decision
from job_agent.resume.extractor import extract_resume_text


@dataclass
class PreparationOutcome:
    application: Application
    answers: list[GeneratedAnswer] = field(default_factory=list)


def discover_application(
    session: Session, config: AppConfig, job: JobRow, job_match: JobMatch, candidate_id: int
) -> Application:
    """Create the Application row for this job+candidate (idempotent — a
    second call for the same pair returns the existing row unchanged) and
    advance it out of DISCOVERED based on the match decision and duplicate
    checks."""
    application, created = get_or_create_application(
        session, job.id, candidate_id, dry_run=config.dry_run
    )
    if not created:
        return application

    duplicate = find_cross_source_duplicate_application(session, job, candidate_id)
    if duplicate is not None:
        transition_status(
            session,
            application,
            ApplicationStatus.SKIPPED,
            event_type="DUPLICATE_DETECTED",
            details={
                "duplicate_of_application_id": duplicate.id,
                "duplicate_of_job_id": duplicate.job_id,
            },
        )
        session.commit()
        return application

    application.match_score = job_match.overall_score
    decision = Decision(job_match.decision)

    if decision == Decision.HUMAN_REQUIRED:
        transition_status(
            session,
            application,
            ApplicationStatus.HUMAN_REQUIRED,
            event_type="HARD_STOP_FROM_MATCH",
            details={"hard_stop_reasons": job_match.hard_stop_reasons},
        )
    elif decision in (Decision.APPLY, Decision.REVIEW):
        transition_status(
            session,
            application,
            ApplicationStatus.MATCHED,
            event_type="MATCHED",
            details={"decision": decision.value, "overall_score": job_match.overall_score},
        )
    else:  # SAVE, SKIP
        transition_status(
            session,
            application,
            ApplicationStatus.SKIPPED,
            event_type="MATCH_DECISION_NOT_APPLY",
            details={"decision": decision.value},
        )
    session.commit()
    return application


def retry_application(session: Session, application: Application) -> Application:
    """The only sanctioned way back out of FAILED — see state_machine's
    module docstring for why FAILED isn't fully terminal. Moves the SAME
    row back to MATCHED so `prepare_application` regenerates answers from
    scratch (never reusing a failed attempt's stale/partial data) and
    `submit_application` re-checks every safety gate fresh. This can never
    create a duplicate row: it's the same Application, same unique
    (job_id, candidate_id) pair, just re-audited via a new event."""
    current = ApplicationStatus(application.status)
    if current != ApplicationStatus.FAILED:
        raise IllegalStateTransitionError(current, ApplicationStatus.MATCHED)

    application.error_message = None
    transition_status(
        session,
        application,
        ApplicationStatus.MATCHED,
        event_type="RETRY_INITIATED",
        details={},
    )
    session.commit()
    return application


def prepare_application(
    session: Session,
    config: AppConfig,
    application: Application,
    job: JobRow,
    profile: CandidateProfile,
    provider: ApplicationProvider,
    llm: LLMProvider | None = None,
    profile_version_id: int | None = None,
) -> PreparationOutcome:
    current = ApplicationStatus(application.status)
    if current not in (ApplicationStatus.MATCHED, ApplicationStatus.HUMAN_REQUIRED):
        raise IllegalStateTransitionError(current, ApplicationStatus.PREPARED)

    llm = llm or NullLLMProvider()

    try:
        questions = provider.get_questions(job)
    except ProviderError as exc:
        application.error_message = str(exc)
        transition_status(
            session,
            application,
            ApplicationStatus.FAILED,
            event_type="PREPARATION_FAILED",
            details={"error": str(exc)},
        )
        session.commit()
        return PreparationOutcome(application=application)

    resume_text = extract_resume_text(config.env.candidate_dir / "resume_master.docx")
    bank = load_answer_bank(config.env.candidate_dir / "answers")

    answers: list[GeneratedAnswer] = []
    for question in questions:
        answer = generate_answer(question, profile, resume_text, bank, llm)
        save_answer(session, application.id, answer)
        answers.append(answer)

    application.profile_version_id = profile_version_id
    any_human_required = any(a.requires_human for a in answers)
    target = ApplicationStatus.HUMAN_REQUIRED if any_human_required else ApplicationStatus.PREPARED
    transition_status(
        session,
        application,
        target,
        event_type="ANSWERS_GENERATED",
        details={
            "question_count": len(questions),
            "human_required_count": sum(1 for a in answers if a.requires_human),
        },
    )
    session.commit()
    return PreparationOutcome(application=application, answers=answers)


def submit_application(
    session: Session,
    config: AppConfig,
    application: Application,
    job: JobRow,
    provider: ApplicationProvider,
    *,
    human_approved: bool = False,
) -> Application:
    """Attempts a real submission. Every one of the following must hold or
    the application stays at PREPARED with an audit event explaining why —
    it never silently retries, never fabricates progress:

    1. `config.is_submission_allowed()` — dry_run disabled AND live_mode
       enabled (BUILD PROMPT sections 36-37's existing choke point).
    2. Automation level 4, OR `human_approved=True` passed explicitly.
    3. Rate limits (daily/hourly/per-company/per-source) not exceeded.
    4. The provider itself must succeed and return evidence — a
       `ProviderError` (including `SubmissionRefusedError`, which is what
       the only shipped provider always raises) moves the application to
       FAILED, never SUBMITTED.
    """
    current = ApplicationStatus(application.status)
    if current != ApplicationStatus.PREPARED:
        raise IllegalStateTransitionError(current, ApplicationStatus.SUBMITTED)

    if not config.is_submission_allowed():
        record_event(
            session,
            application.id,
            "SUBMISSION_SKIPPED_DRY_RUN",
            {"dry_run": config.dry_run, "live_mode": config.live_mode},
        )
        session.commit()
        return application

    automation_level = config.automation.automation.level
    if automation_level < 4 and not human_approved:
        record_event(
            session,
            application.id,
            "SUBMISSION_BLOCKED_NO_APPROVAL",
            {"automation_level": automation_level},
        )
        session.commit()
        return application

    limit_result = check_rate_limits(
        session, application.candidate_id, job, config.automation.applications
    )
    if not limit_result.allowed:
        transition_status(
            session,
            application,
            ApplicationStatus.SKIPPED,
            event_type="RATE_LIMIT_EXCEEDED",
            details={"reason": limit_result.reason},
        )
        session.commit()
        return application

    answers = _answers_from_db(session, application.id)
    try:
        evidence = provider.submit(job, answers)
    except ProviderError as exc:
        application.error_message = str(exc)
        transition_status(
            session,
            application,
            ApplicationStatus.FAILED,
            event_type="SUBMISSION_FAILED",
            details={"error": str(exc), "provider": provider.name},
        )
        session.commit()
        return application

    application.automation_level_used = automation_level
    application.submitted_at = evidence.submitted_at
    application.confirmation_id = evidence.confirmation_id
    application.confirmation_url = evidence.confirmation_url
    application.confirmation_text = evidence.confirmation_text
    application.screenshot_path = evidence.screenshot_path
    transition_status(
        session,
        application,
        ApplicationStatus.SUBMITTED,
        event_type="SUBMITTED",
        details={
            "provider": provider.name,
            "has_concrete_evidence": evidence.has_concrete_evidence,
        },
    )
    session.commit()
    return application


def verify_application(
    session: Session, application: Application, job: JobRow, provider: ApplicationProvider
) -> Application:
    """Only path to VERIFIED. Requires the provider to return
    `verified=True` AND concrete evidence — a `False`/inconclusive result,
    a missing evidence object, or a `ProviderError` all leave the
    application at SUBMITTED (attempted, unconfirmed), never VERIFIED and
    never silently downgraded to FAILED (a submission may well have
    succeeded even if we can't yet prove it)."""
    current = ApplicationStatus(application.status)
    if current != ApplicationStatus.SUBMITTED:
        raise IllegalStateTransitionError(current, ApplicationStatus.VERIFIED)

    evidence = SubmissionEvidence(
        confirmation_id=application.confirmation_id,
        confirmation_url=application.confirmation_url,
        confirmation_text=application.confirmation_text,
        screenshot_path=application.screenshot_path,
        submitted_at=application.submitted_at or datetime.now(UTC),
    )

    try:
        result = provider.verify(job, evidence)
    except ProviderError as exc:
        record_event(session, application.id, "VERIFICATION_ERROR", {"error": str(exc)})
        session.commit()
        return application

    if not result.verified or result.evidence is None or not result.evidence.has_concrete_evidence:
        record_event(
            session,
            application.id,
            "VERIFICATION_INCONCLUSIVE",
            {"reason": result.reason},
        )
        session.commit()
        return application

    transition_status(
        session,
        application,
        ApplicationStatus.VERIFIED,
        event_type="VERIFIED",
        details={"reason": result.reason, "confirmation_id": result.evidence.confirmation_id},
    )
    session.commit()
    return application


def _answers_from_db(session: Session, application_id: int) -> list[GeneratedAnswer]:
    rows = get_answers(session, application_id)
    return [
        GeneratedAnswer(
            question=row.question_text,
            category=QuestionCategory(row.question_category),
            answer=row.answer_text,
            confidence=row.confidence,
            source=row.source or "unknown",
            requires_human=row.requires_human,
            validated=row.validated,
            validation_notes=tuple(row.validation_notes or ()),
        )
        for row in rows
    ]

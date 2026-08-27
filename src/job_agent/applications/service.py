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

Phase 6A adds two things to this module, both purely additive — no
existing function's signature or behavior changes:

* **`handle_application_inspection`** — the only place
  `job_agent.applications.rules_enforcement.evaluate_inspection`'s verdict
  is applied to a real `Application` row, per the "provider reports, core
  decides" boundary described in `job_agent.applications.provider`.
* **`prepare_applications_batch` / `submit_applications_batch`** — per-item
  failure isolation for the CLI's `applications prepare`/`applications
  run` commands, following the exact pattern `job_agent.jobs.service.
  scan_source` already uses for job sources: catch, log, roll back,
  continue — one bad item can never abort the rest of the batch.

Security fix (post-Phase-6A audit): every raw exception message this
module captures (`str(exc)`) is scrubbed through `job_agent.logging.
setup.redact_text()` before it can reach a DB column
(`Application.error_message`), a log line, or a `BatchItemOutcome` the
CLI prints verbatim — a credential embedded in a future provider's
exception message (an HTTP client error, for instance) can no longer
leak through any of those three surfaces. `details={"error": str(exc)}`
dicts passed to `record_event()`/`transition_status()` are additionally
redacted centrally inside `record_event()` itself, so the audit trail
persisted to `application_events` is protected the same way.
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
from job_agent.applications.rules_enforcement import evaluate_inspection
from job_agent.applications.schema import (
    ApplicationInspection,
    ApplicationStatus,
    GeneratedAnswer,
    QuestionCategory,
    SubmissionEvidence,
)
from job_agent.applications.state_machine import IllegalStateTransitionError, can_transition
from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig
from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.llm.provider import LLMProvider, NullLLMProvider
from job_agent.logging.setup import get_logger, log_event, redact_text
from job_agent.matching.schema import Decision
from job_agent.resume.extractor import extract_resume_text

logger = get_logger("job_agent.applications.service")


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

    # Phase 6B: inspection is capability-driven (`provider.
    # supports_inspection`), never assumed. A provider that never opted in
    # (every Phase 5/6A provider, and any future one that doesn't
    # implement real structural inspection) is left on the exact Phase
    # 5/6A code path below, unchanged. See `ApplicationProvider.
    # supports_inspection`'s docstring for why an unconditional call here
    # would be a correctness regression, not a safety improvement.
    if provider.supports_inspection:
        try:
            discovery_target = provider.discover_application(job)
            inspection = provider.inspect_application(job, discovery_target)
        except ProviderError as exc:
            # error_message is a plain DB column, not routed through
            # record_event()'s redaction — must be scrubbed here explicitly.
            application.error_message = redact_text(str(exc))
            transition_status(
                session,
                application,
                ApplicationStatus.FAILED,
                event_type="INSPECTION_FAILED",
                details={"error": str(exc)},
            )
            session.commit()
            return PreparationOutcome(application=application)

        # `inspection` carries untrusted external content (field labels/
        # descriptions the provider parsed) only inside `detail`, a plain
        # diagnostic string — never inside the boolean facts
        # `evaluate_inspection` actually decides on. Passing it straight
        # through changes nothing about that boundary: the provider
        # reports facts, `evaluate_inspection` (real `config.rules.
        # safety`, never a provider-side copy) is still the only place a
        # HUMAN_REQUIRED-from-inspection decision is made.
        verdict = evaluate_inspection(config.rules, inspection)
        application = handle_application_inspection(session, config, application, inspection)
        if verdict.human_required:
            # A safety gate, not merely informational — matches how every
            # other gate in this module (submit_application's dry_run/
            # approval/rate-limit checks) short-circuits rather than
            # proceeding past a failed check. A human must resolve
            # CAPTCHA/MFA/consent/an unrecognized form before answer
            # generation is even meaningful.
            return PreparationOutcome(application=application)

    try:
        questions = provider.get_questions(job)
    except ProviderError as exc:
        # error_message is a plain DB column, not routed through
        # record_event()'s redaction — must be scrubbed here explicitly.
        application.error_message = redact_text(str(exc))
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
        # error_message is a plain DB column, not routed through
        # record_event()'s redaction — must be scrubbed here explicitly.
        application.error_message = redact_text(str(exc))
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


def handle_application_inspection(
    session: Session,
    config: AppConfig,
    application: Application,
    inspection: ApplicationInspection,
) -> Application:
    """Applies `rules_enforcement.evaluate_inspection`'s verdict to a real
    Application row — the only place a provider-reported structural fact
    (CAPTCHA/MFA/unrecognized form) is translated into a HUMAN_REQUIRED
    transition. The provider that produced `inspection` never calls this
    itself and has no path to; see `job_agent.applications.provider`'s
    module docstring for why that boundary matters.

    Raises `IllegalStateTransitionError` if the application isn't in a
    state HUMAN_REQUIRED can legally be reached from (e.g. already
    VERIFIED/SKIPPED) — this function does not silently no-op on a caller
    error, it surfaces it exactly like every other transition in this
    module.
    """
    current = ApplicationStatus(application.status)
    verdict = evaluate_inspection(config.rules, inspection)

    if not verdict.human_required:
        record_event(
            session,
            application.id,
            "INSPECTION_PASSED",
            {"detail": inspection.detail},
        )
        session.commit()
        return application

    if not can_transition(current, ApplicationStatus.HUMAN_REQUIRED):
        raise IllegalStateTransitionError(current, ApplicationStatus.HUMAN_REQUIRED)

    transition_status(
        session,
        application,
        ApplicationStatus.HUMAN_REQUIRED,
        event_type=verdict.reason.upper() if verdict.reason else "INSPECTION_HUMAN_REQUIRED",
        details={"reason": verdict.reason, "inspection_detail": inspection.detail},
    )
    session.commit()
    return application


@dataclass
class BatchItemOutcome:
    """Result of processing one job/application within a batch — see
    `prepare_applications_batch`/`submit_applications_batch`. `error` is
    set only when processing this one item raised; a set `error` means
    `application` reflects whatever state existed before the failure
    (possibly `None` if the row was never even reached), never a guessed
    or partially-applied result."""

    job: JobRow
    application: Application | None
    error: str | None = None


def prepare_applications_batch(
    session: Session,
    config: AppConfig,
    items: list[tuple[JobRow, JobMatch]],
    candidate_id: int,
    profile: CandidateProfile,
    provider: ApplicationProvider,
    llm: LLMProvider | None = None,
) -> list[BatchItemOutcome]:
    """Runs `discover_application` + `prepare_application` for each
    (job, job_match) pair, isolating failures exactly like
    `job_agent.jobs.service.scan_source` isolates one job source's
    failure from the rest of a scan: one bad item is caught, logged, and
    rolled back so it can never abort the remaining items — and never
    leaves a half-flushed row from the failed item polluting the next
    item's transaction.
    """
    results: list[BatchItemOutcome] = []
    for job, job_match in items:
        try:
            application = discover_application(session, config, job, job_match, candidate_id)
            if ApplicationStatus(application.status) in (
                ApplicationStatus.MATCHED,
                ApplicationStatus.HUMAN_REQUIRED,
            ):
                outcome = prepare_application(
                    session, config, application, job, profile, provider, llm=llm
                )
                application = outcome.application
            results.append(BatchItemOutcome(job=job, application=application))
        except Exception as exc:  # noqa: BLE001 — isolate one bad item from the rest of the batch
            session.rollback()
            # Scrubbed once and reused for both the log line and the
            # returned outcome, so the CLI (which prints outcome.error
            # verbatim) and the logs are protected by the same pass —
            # log_event() would also redact `error=` on its own, but
            # BatchItemOutcome.error does not flow through log_event() at
            # all, so it needs its own explicit scrub.
            safe_error = redact_text(str(exc))
            log_event(
                logger,
                component="applications.service",
                action="prepare_applications_batch_item",
                result="failure",
                job_id=job.id,
                error=safe_error,
            )
            results.append(BatchItemOutcome(job=job, application=None, error=safe_error))
    return results


def submit_applications_batch(
    session: Session,
    config: AppConfig,
    items: list[tuple[Application, JobRow]],
    provider: ApplicationProvider,
    *,
    human_approved: bool = False,
) -> list[BatchItemOutcome]:
    """Runs `submit_application` for each (application, job) pair with the
    same per-item isolation as `prepare_applications_batch` — a single
    application's failure never prevents the rest of the batch from being
    attempted."""
    results: list[BatchItemOutcome] = []
    for application, job in items:
        try:
            result = submit_application(
                session, config, application, job, provider, human_approved=human_approved
            )
            results.append(BatchItemOutcome(job=job, application=result))
        except Exception as exc:  # noqa: BLE001 — isolate one bad item from the rest of the batch
            session.rollback()
            safe_error = redact_text(str(exc))
            log_event(
                logger,
                component="applications.service",
                action="submit_applications_batch_item",
                result="failure",
                job_id=job.id,
                application_id=application.id,
                error=safe_error,
            )
            results.append(BatchItemOutcome(job=job, application=None, error=safe_error))
    return results

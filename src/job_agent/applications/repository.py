"""Persistence for the application engine.

Two invariants this module exists to guarantee:

* **No status change without an audit record.** `transition_status()` is
  the only function that may change `Application.status`, and it always
  writes a matching `ApplicationEvent` row in the same call — there is no
  code path that updates status without also recording why (BUILD PROMPT
  section 53).
* **No duplicate application.** `get_or_create_application()` checks for
  an existing row first and the DB's own unique constraint on
  `(job_id, candidate_id)` (see db/models.py) backs it up — even a racing
  concurrent call cannot create two Application rows for the same job.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.applications.schema import ApplicationStatus, GeneratedAnswer
from job_agent.applications.state_machine import validate_transition
from job_agent.db.models import Application, ApplicationAnswer, ApplicationEvent


def get_application(session: Session, job_id: int, candidate_id: int) -> Application | None:
    return session.execute(
        select(Application).where(
            Application.job_id == job_id, Application.candidate_id == candidate_id
        )
    ).scalar_one_or_none()


def get_or_create_application(
    session: Session, job_id: int, candidate_id: int, *, dry_run: bool
) -> tuple[Application, bool]:
    """Returns (application, created). Never creates a second row for the
    same (job_id, candidate_id) — the DB unique constraint is the final
    backstop if this check ever races."""
    existing = get_application(session, job_id, candidate_id)
    if existing is not None:
        return existing, False

    application = Application(
        job_id=job_id,
        candidate_id=candidate_id,
        status=ApplicationStatus.DISCOVERED.value,
        dry_run=dry_run,
    )
    session.add(application)
    session.flush()
    record_event(
        session, application.id, "APPLICATION_DISCOVERED", {"job_id": job_id}
    )
    return application, True


def record_event(
    session: Session, application_id: int, event_type: str, details: dict
) -> ApplicationEvent:
    event = ApplicationEvent(application_id=application_id, event_type=event_type, details=details)
    session.add(event)
    session.flush()
    return event


def transition_status(
    session: Session,
    application: Application,
    target: ApplicationStatus,
    *,
    event_type: str,
    details: dict | None = None,
) -> Application:
    """The only sanctioned way to change `Application.status`.

    Raises `IllegalStateTransitionError` (from `state_machine.
    validate_transition`) rather than silently allowing an unsafe jump —
    e.g. straight from MATCHED to VERIFIED.
    """
    current = ApplicationStatus(application.status)
    validate_transition(current, target)

    application.status = target.value
    session.flush()
    record_event(
        session,
        application.id,
        event_type,
        {**(details or {}), "from_status": current.value, "to_status": target.value},
    )
    return application


def save_answer(
    session: Session, application_id: int, answer: GeneratedAnswer
) -> ApplicationAnswer:
    row = ApplicationAnswer(
        application_id=application_id,
        question_text=answer.question,
        question_category=answer.category.value,
        answer_text=answer.answer,
        confidence=answer.confidence,
        requires_human=answer.requires_human,
        source=answer.source,
        validated=answer.validated,
        validation_notes=list(answer.validation_notes),
    )
    session.add(row)
    session.flush()
    return row


def get_answers(session: Session, application_id: int) -> list[ApplicationAnswer]:
    return list(
        session.execute(
            select(ApplicationAnswer).where(ApplicationAnswer.application_id == application_id)
        ).scalars()
    )


# --------------------------------------------------------------------------
# Rate limiting queries — BUILD PROMPT section 43 / config/automation.yaml
# --------------------------------------------------------------------------
def count_submissions_since(session: Session, candidate_id: int, since: datetime) -> int:
    rows = session.execute(
        select(Application).where(
            Application.candidate_id == candidate_id,
            Application.submitted_at.is_not(None),
            Application.submitted_at >= since,
        )
    ).scalars()
    return len(list(rows))


def count_submissions_to_company(
    session: Session, candidate_id: int, company_name: str, *, since: datetime | None = None
) -> int:
    """`since=None` counts all-time — `max_per_company` in config/
    automation.yaml has no time qualifier in its name, unlike max_per_day/
    max_per_hour, so it's treated as a lifetime cap, not a rolling one."""
    from job_agent.db.models import Job as JobRow

    conditions = [
        Application.candidate_id == candidate_id,
        Application.submitted_at.is_not(None),
        JobRow.company_name == company_name,
    ]
    if since is not None:
        conditions.append(Application.submitted_at >= since)
    rows = session.execute(
        select(Application).join(JobRow, Application.job_id == JobRow.id).where(*conditions)
    ).scalars()
    return len(list(rows))


def count_submissions_from_source_since(
    session: Session, candidate_id: int, source_id: int, since: datetime
) -> int:
    from job_agent.db.models import Job as JobRow

    rows = session.execute(
        select(Application)
        .join(JobRow, Application.job_id == JobRow.id)
        .where(
            Application.candidate_id == candidate_id,
            Application.submitted_at.is_not(None),
            Application.submitted_at >= since,
            JobRow.source_id == source_id,
        )
    ).scalars()
    return len(list(rows))


def utcnow() -> datetime:
    return datetime.now(UTC)

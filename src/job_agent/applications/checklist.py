"""Application checklist — Career OS FINAL GOD MODE Part 4.12.

Every item is either derived from data the automation pipeline or the
matcher already produced (resume selection/tailoring, submission,
confirmation) or a plain manual toggle the candidate controls
(`Application.cover_letter_ready`/`questions_prepared` — there is no
reliable automatic signal for either, since cover letters are generated
on demand and never persisted, and question prep happens outside the
system entirely). Nothing here is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.db.models import Application, Resume

_SUBMITTED_PIPELINE_STAGES = {"APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED"}


@dataclass(frozen=True)
class ApplicationChecklist:
    resume_selected: bool
    resume_tailored: bool
    cover_letter_ready: bool
    questions_prepared: bool
    submitted: bool
    confirmation_received: bool


def compute_checklist(application: Application, resume: Resume | None) -> ApplicationChecklist:
    return ApplicationChecklist(
        resume_selected=application.resume_id is not None,
        resume_tailored=bool(resume is not None and resume.is_tailored),
        cover_letter_ready=application.cover_letter_ready,
        questions_prepared=application.questions_prepared,
        submitted=(
            application.status == "SUBMITTED"
            or application.submitted_at is not None
            or application.pipeline_stage in _SUBMITTED_PIPELINE_STAGES
        ),
        confirmation_received=bool(application.confirmation_id or application.confirmation_url),
    )

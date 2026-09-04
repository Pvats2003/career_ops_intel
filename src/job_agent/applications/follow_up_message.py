"""Follow-up message generator — Career OS FINAL GOD MODE Part 4.14.

Turns a `FollowUpRecommendation` into an actual, ready-to-send message —
not just "you should follow up" but the concrete words to say. Entirely
deterministic and templated from facts already on the application/job
(candidate name, job title, company, pipeline stage, days waiting,
recruiter contact if known) — nothing here is invented, and nothing here
is ever sent: BUILD PROMPT Phase 13's "do not contact recruiters
automatically" still holds. The candidate copies this and sends it
themselves, or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.applications.follow_up import FollowUpRecommendation

_STAGE_CONTEXT: dict[str, str] = {
    "APPLIED": "I haven't heard back yet and wanted to check in",
    "ASSESSMENT": "I wanted to check in on the status of the assessment",
    "INTERVIEW": "I wanted to follow up after our interview",
}


@dataclass(frozen=True)
class FollowUpMessage:
    subject: str
    body: str


def generate_follow_up_message(
    recommendation: FollowUpRecommendation, candidate_name: str
) -> FollowUpMessage:
    job = recommendation.job
    application = recommendation.application
    context = _STAGE_CONTEXT.get(
        application.pipeline_stage, "I wanted to check in on my application"
    )
    greeting = f"Hi {application.recruiter_contact}," if application.recruiter_contact else "Hello,"

    subject = f"Following up: {job.title} application"
    body = (
        f"{greeting}\n\n"
        f"I applied for the {job.title} role at {job.company_name} "
        f"about {recommendation.applied_days_ago} days ago — {context}, and remain "
        f"very interested in the opportunity. Please let me know if there's any "
        f"additional information I can provide in the meantime.\n\n"
        f"Best regards,\n{candidate_name}"
    )
    return FollowUpMessage(subject=subject, body=body)

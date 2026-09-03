"""Follow-up intelligence — Career OS Phase 13.

Surfaces "FOLLOW-UP RECOMMENDED" for an application whose `pipeline_stage`
(the candidate's own real-world recruiting-process tracker — see
`Application`'s docstring in `job_agent.db.models`) has gone stale: no
stage change in `stale_after_days`. There is no dedicated "applied at"
timestamp on `Application` — `updated_at` (bumped every time
`pipeline_stage` changes, via `TimestampMixin`) is the one real signal
this system has for "how long has this application sat in its current
stage", so that's what `applied_days_ago` measures here, despite its
name (kept matching the existing `FollowUpRecommendationOut` schema
field). This module NEVER contacts a recruiter or drafts outreach —
"Do not contact recruiters automatically" (BUILD PROMPT Phase 13) — it
only flags what a human should look at.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow

# Stages where a human is actively waiting on the other side to respond —
# a stale SAVED/SHORTLISTED (never applied) or a terminal OFFER/REJECTED
# is never a follow-up candidate.
_ACTIVE_WAITING_STAGES = frozenset({"APPLIED", "ASSESSMENT", "INTERVIEW"})

_SUGGESTED_ACTIONS: dict[str, str] = {
    "APPLIED": "No response yet — consider a polite follow-up on your application status.",
    "ASSESSMENT": "Assessment stage has been quiet — check in on next steps.",
    "INTERVIEW": "No update since your last interview stage — follow up on the outcome.",
}


@dataclass(frozen=True)
class FollowUpRecommendation:
    application: ApplicationRow
    job: JobRow
    applied_days_ago: int
    suggested_action: str


def compute_follow_up_recommendations(
    applications_with_jobs: list[tuple[ApplicationRow, JobRow]],
    *,
    stale_after_days: int = 7,
) -> list[FollowUpRecommendation]:
    now = datetime.now(UTC)
    recommendations = []
    for application, job in applications_with_jobs:
        if application.pipeline_stage not in _ACTIVE_WAITING_STAGES:
            continue
        last_update = application.updated_at
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=UTC)
        days_since = (now - last_update).days
        if days_since < stale_after_days:
            continue
        recommendations.append(
            FollowUpRecommendation(
                application=application, job=job, applied_days_ago=days_since,
                suggested_action=_SUGGESTED_ACTIONS[application.pipeline_stage],
            )
        )
    recommendations.sort(key=lambda r: r.applied_days_ago, reverse=True)
    return recommendations

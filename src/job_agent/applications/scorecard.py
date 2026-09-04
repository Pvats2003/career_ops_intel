"""Application scorecard — Career OS FINAL GOD MODE Part 4.11.

Rolls up the four questions a candidate actually asks before spending
time on an application — "do I fit?", "is the data behind this job any
good?", "is it worth my career?", "can I actually apply?" — into one
scorecard. Entirely derived from data already computed elsewhere (the
match, `job_agent.jobs.confidence`, `job_agent.jobs.viability`) — never a
second, independent judgment about the job.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch
from job_agent.jobs.confidence import assess_data_confidence
from job_agent.jobs.viability import assess_application_viability

# Mirrors `job_agent.matching.ranking._CAREER_VALUE_SIGNAL` in spirit (the
# matcher's own decision is the one real, already-computed proxy for
# career value) but kept local and on a 0-100 scale — this module has no
# business importing ranking's private weighting internals.
_CAREER_VALUE_SCORE: dict[str, float] = {
    "APPLY": 100.0,
    "REVIEW": 65.0,
    "HUMAN_REQUIRED": 45.0,
    "SAVE": 30.0,
    "SKIP": 0.0,
}

_VIABILITY_SCORE: dict[str, float] = {
    "VIABLE": 100.0,
    "CAUTION": 55.0,
    "BLOCKED": 0.0,
}


@dataclass(frozen=True)
class ApplicationScorecard:
    candidate_fit: float
    job_quality: float
    career_value: float
    application_viability: float
    overall_score: float
    overall_recommendation: str


def compute_scorecard(job: JobRow, match: JobMatch | None) -> ApplicationScorecard:
    candidate_fit = float(match.overall_score) if match else 0.0

    confidence = assess_data_confidence(job)
    job_quality = 100.0 if confidence.level == "High" else 60.0

    career_value = _CAREER_VALUE_SCORE.get(match.decision, 0.0) if match else 0.0

    viability = assess_application_viability(job, match)
    viability_score = _VIABILITY_SCORE[viability.overall]

    overall_score = round(
        0.4 * candidate_fit + 0.15 * job_quality + 0.2 * career_value + 0.25 * viability_score,
        1,
    )

    if match is None:
        overall_recommendation = "Not yet matched against your profile."
    elif viability.overall == "BLOCKED":
        overall_recommendation = "Not viable to apply right now — fix the blocker first."
    elif match.decision == "APPLY" and viability.overall == "VIABLE":
        overall_recommendation = "Apply — strong fit and nothing blocking you."
    elif overall_score >= 60:
        overall_recommendation = "Worth applying, with some caveats to weigh first."
    else:
        overall_recommendation = "Lower priority — weaker fit or real viability concerns."

    return ApplicationScorecard(
        candidate_fit=candidate_fit,
        job_quality=job_quality,
        career_value=career_value,
        application_viability=viability_score,
        overall_score=overall_score,
        overall_recommendation=overall_recommendation,
    )

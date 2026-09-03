"""Opportunity ranking — Career OS Phase 8 sections 9-10 (Today's Top 10 /
Apply Now). Combines the candidate-fit score `job_agent.matching` already
computes with freshness, career value, application viability, and company
fit into ONE composite score, using the exact weights already defined in
`config/automation.yaml`'s `priority_weights` block (`job_agent.config.
models.PriorityWeights`) — never a second, ad-hoc weighting scheme.

This module only RANKS jobs the matching engine already scored; it never
computes a match score itself and never calls an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.config.models import PriorityWeights
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow

_FRESHNESS_SIGNAL: dict[str, float] = {
    "JUST_POSTED": 1.0,
    "NEW": 0.8,
    "RECENT": 0.5,
    "OLD": 0.2,
    "UNKNOWN_POST_DATE": 0.3,
}

# Reuses the matching engine's own decision as the "is this worth my
# career trajectory" signal — the deterministic+semantic matcher already
# reasons about role alignment/experience/project relevance (BUILD PROMPT
# section 6's "career trajectory" factor lives there), so this is the one
# real, already-computed proxy for career value rather than a second,
# unfounded score.
_CAREER_VALUE_SIGNAL: dict[str, float] = {
    "APPLY": 1.0,
    "REVIEW": 0.65,
    "HUMAN_REQUIRED": 0.45,
    "SAVE": 0.3,
    "SKIP": 0.0,
}


@dataclass(frozen=True)
class RankedJob:
    job: JobRow
    match: JobMatchRow | None
    rank_score: float
    why: tuple[str, ...]
    gaps: tuple[str, ...]
    recommendation: str


def _company_fit_signal(job: JobRow) -> float:
    """Neutral until `job_agent.web.routers.companies` (Phase 10) computes
    a real per-company fit score from actual signals — never fabricated
    here; 0.5 is a deliberate "no opinion either way" midpoint, not a
    disguised real score."""
    return 0.5


def _application_ease_signal(job: JobRow) -> float:
    return 1.0 if job.application_url else 0.3


def rank_score(job: JobRow, match: JobMatchRow | None, weights: PriorityWeights) -> float:
    match_signal = (match.overall_score / 100) if match else 0.0
    freshness_signal = _FRESHNESS_SIGNAL.get(job.freshness_status, 0.3)
    career_signal = _CAREER_VALUE_SIGNAL.get(match.decision, 0.0) if match else 0.0
    company_signal = _company_fit_signal(job)
    ease_signal = _application_ease_signal(job)

    return round(
        100
        * (
            weights.match * match_signal
            + weights.freshness * freshness_signal
            + weights.career_value * career_signal
            + weights.company_fit * company_signal
            + weights.application_ease * ease_signal
        ),
        1,
    )


def explain(job: JobRow, match: JobMatchRow | None) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """(why, gaps, recommendation) — grounded entirely in the match's own
    `reasoning`/`missing_requirements`/`concerns` fields (never invented
    here) plus the job's freshness label."""
    why: list[str] = []
    gaps: list[str] = []
    if match is not None:
        if match.reasoning:
            why.append(match.reasoning)
        gaps.extend(match.missing_requirements or [])
        gaps.extend(match.concerns or [])
    if job.freshness_status in ("JUST_POSTED", "NEW"):
        why.append("Freshly posted — early applications are often reviewed first.")
    if not job.application_url:
        gaps.append("No direct application link found for this posting.")

    if match is not None and match.decision == "APPLY":
        recommendation = "Apply today."
    elif match is not None and match.decision == "REVIEW":
        recommendation = "Worth a closer look before applying."
    elif match is not None and match.decision == "HUMAN_REQUIRED":
        recommendation = "Needs your review — the matcher flagged something to check."
    else:
        recommendation = "Lower priority for now."

    return tuple(why), tuple(gaps), recommendation


def rank_jobs(
    jobs_with_matches: list[tuple[JobRow, JobMatchRow | None]],
    weights: PriorityWeights,
    *,
    limit: int | None = None,
) -> list[RankedJob]:
    """Ranks ACTIVE jobs only (never recommends a CLOSED/EXPIRED posting —
    section 7) by composite `rank_score`, highest first."""
    ranked = []
    for job, match in jobs_with_matches:
        if job.lifecycle_status != "ACTIVE":
            continue
        score = rank_score(job, match, weights)
        why, gaps, recommendation = explain(job, match)
        ranked.append(RankedJob(job=job, match=match, rank_score=score, why=why, gaps=gaps,
                                 recommendation=recommendation))
    ranked.sort(key=lambda r: r.rank_score, reverse=True)
    return ranked[:limit] if limit is not None else ranked

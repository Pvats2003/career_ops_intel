"""Decision engine — BUILD PROMPT section 11.

Threshold-based by default, but hard-stop conditions and candidate-
configured exclusions always override the numeric score, and a job whose
semantic stage couldn't run is deliberately capped below APPLY: quality
over quantity means auto-applying without the semantic "second opinion" is
not a risk worth taking, even at a high deterministic score.
"""

from __future__ import annotations

from job_agent.config.models import MatchingThresholds
from job_agent.matching.schema import Decision, JobMatchResult
from job_agent.matching.scoring import ScoredMatch


def decide(scored: ScoredMatch, thresholds: MatchingThresholds) -> Decision:
    if scored.excluded_reasons:
        return Decision.SKIP
    if scored.hard_stop_reasons:
        return Decision.HUMAN_REQUIRED

    if scored.overall_score >= thresholds.auto_apply_threshold:
        return Decision.APPLY if scored.semantic_available else Decision.REVIEW
    if scored.overall_score >= thresholds.review_threshold:
        return Decision.REVIEW
    if scored.overall_score >= thresholds.save_threshold:
        return Decision.SAVE
    return Decision.SKIP


def finalize(scored: ScoredMatch, thresholds: MatchingThresholds) -> JobMatchResult:
    return JobMatchResult(
        overall_score=scored.overall_score,
        decision=decide(scored, thresholds),
        skills_match=scored.skills_match,
        experience_match=scored.experience_match,
        role_match=scored.role_match,
        project_match=scored.project_match,
        education_match=scored.education_match,
        location_match=scored.location_match,
        seniority_match=scored.seniority_match,
        eligibility_match=scored.eligibility_match,
        missing_requirements=tuple(scored.missing_requirements),
        concerns=tuple(scored.concerns),
        reasoning=scored.reasoning,
        hard_stop_reasons=tuple(scored.hard_stop_reasons),
        excluded_reasons=tuple(scored.excluded_reasons),
        semantic_available=scored.semantic_available,
        prompt_version=scored.prompt_version,
        model_used=scored.model_used,
    )

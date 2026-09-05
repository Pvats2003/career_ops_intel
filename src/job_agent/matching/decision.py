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

# Matching Engine V2 (audit item H): production has no LLM configured, so
# "semantic didn't run" can no longer be the ONLY way to unlock APPLY —
# that would make APPLY permanently unreachable for every deterministic-
# only deployment regardless of how strong the evidence actually is.
# Deterministic-only evidence can unlock APPLY, but only when it is
# genuinely strong: a primary-tier role-family match (not a marginal or
# adjacent-but-unconfirmed one), real specific-skill evidence (not just
# generic keyword overlap), and zero risk flags of any kind. When semantic
# DID run, it still counts as an independent, sufficient path to APPLY —
# exactly as before — since that's real additional confirmation on top of
# the deterministic score, never a requirement for it.
_DETERMINISTIC_APPLY_MIN_ROLE_MATCH = 85
_DETERMINISTIC_APPLY_MIN_SPECIFIC_MATCHES = 2


def _deterministic_confidence_is_high(scored: ScoredMatch) -> bool:
    return (
        not scored.risk_flags
        and scored.role_match >= _DETERMINISTIC_APPLY_MIN_ROLE_MATCH
        and scored.specific_matched_count >= _DETERMINISTIC_APPLY_MIN_SPECIFIC_MATCHES
    )


def decide(scored: ScoredMatch, thresholds: MatchingThresholds) -> Decision:
    if scored.excluded_reasons:
        return Decision.SKIP
    if scored.hard_stop_reasons:
        return Decision.HUMAN_REQUIRED

    if scored.overall_score >= thresholds.auto_apply_threshold:
        if scored.semantic_available or _deterministic_confidence_is_high(scored):
            return Decision.APPLY
        return Decision.REVIEW
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
        raw_fit_score=scored.raw_fit_score,
        risk_flags=tuple(scored.risk_flags),
    )

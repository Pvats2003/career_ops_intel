"""Combines deterministic + (optional) semantic sub-scores into the final
`JobMatchResult`, per the weights in config/automation.yaml.

Only three dimensions are semantic-refinable — role_match, experience_match,
project_match — matching BUILD PROMPT section 10's own split of what's
deterministic (skills, education, location, seniority, eligibility) vs.
semantic (role alignment, experience similarity, project relevance,
transferable skills, career trajectory). Blending is a simple weighted
average (`semantic_blend_weight`), not a replacement — a bad semantic score
can pull a strong deterministic one down (and vice versa), which is the
intended "second opinion" role of the semantic stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.config.models import ScoringWeights
from job_agent.matching.deterministic import DeterministicMatch
from job_agent.matching.semantic import SemanticOutcome


@dataclass
class ScoredMatch:
    """Everything a `JobMatchResult` needs except `decision` — computing the
    decision requires thresholds this module doesn't own (see
    `job_agent.matching.decision.finalize`)."""

    overall_score: int
    skills_match: int
    experience_match: int
    role_match: int
    project_match: int
    education_match: int
    location_match: int
    seniority_match: int
    eligibility_match: int
    missing_requirements: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    reasoning: str = ""
    hard_stop_reasons: list[str] = field(default_factory=list)
    excluded_reasons: list[str] = field(default_factory=list)
    semantic_available: bool = False
    prompt_version: str | None = None
    model_used: str | None = None


def _blend(deterministic_score: int, semantic_score: int, weight: float) -> int:
    return round(deterministic_score * (1 - weight) + semantic_score * weight)


def combine_match(
    deterministic: DeterministicMatch,
    semantic: SemanticOutcome,
    *,
    weights: ScoringWeights,
    semantic_blend_weight: float,
) -> ScoredMatch:
    role_match = deterministic.role_match
    experience_match = deterministic.experience_match
    project_match = deterministic.project_match
    concerns = list(deterministic.concerns)
    missing = list(deterministic.missing_requirements)
    reasoning_parts = [
        f"Deterministic: skills={deterministic.skills_match}, "
        f"experience={deterministic.experience_match}, role={deterministic.role_match}, "
        f"project={deterministic.project_match}, education={deterministic.education_match}, "
        f"location={deterministic.location_match}, seniority={deterministic.seniority_match}, "
        f"eligibility={deterministic.eligibility_match}."
    ]

    prompt_version = None
    model_used = None

    if semantic.available and semantic.result is not None:
        sem = semantic.result
        role_match = _blend(role_match, sem.role_alignment_score, semantic_blend_weight)
        experience_match = _blend(
            experience_match, sem.experience_similarity_score, semantic_blend_weight
        )
        project_match = _blend(project_match, sem.project_relevance_score, semantic_blend_weight)
        concerns.extend(sem.additional_concerns)
        missing.extend(sem.additional_missing_requirements)
        if sem.transferable_skills:
            skills_note = ", ".join(sem.transferable_skills)
            reasoning_parts.append(f"Transferable skills noted: {skills_note}.")
        reasoning_parts.append(f"Semantic: {sem.reasoning}")
        if semantic.metadata:
            prompt_version = semantic.metadata.prompt_version
            model_used = semantic.metadata.model
    else:
        concerns.append(
            f"Semantic matching unavailable ({semantic.unavailable_reason}); "
            "role/experience/project scores are deterministic-only."
        )
        reasoning_parts.append("Semantic matching skipped — deterministic scores only.")

    sub_scores = {
        "skills_match": deterministic.skills_match,
        "experience_match": experience_match,
        "role_match": role_match,
        "project_match": project_match,
        "education_match": deterministic.education_match,
        "location_match": deterministic.location_match,
        "seniority_match": deterministic.seniority_match,
        "eligibility_match": deterministic.eligibility_match,
    }

    overall_score = round(
        sub_scores["skills_match"] * weights.skills
        + sub_scores["experience_match"] * weights.experience
        + sub_scores["role_match"] * weights.role_alignment
        + sub_scores["project_match"] * weights.projects
        + sub_scores["education_match"] * weights.education
        + sub_scores["location_match"] * weights.location
        + sub_scores["seniority_match"] * weights.seniority
        + sub_scores["eligibility_match"] * weights.eligibility
    )
    overall_score = max(0, min(100, overall_score))

    return ScoredMatch(
        overall_score=overall_score,
        **sub_scores,
        missing_requirements=list(dict.fromkeys(missing)),
        concerns=list(dict.fromkeys(concerns)),
        reasoning=" ".join(reasoning_parts),
        hard_stop_reasons=list(deterministic.hard_stop_reasons),
        excluded_reasons=list(deterministic.excluded_reasons),
        semantic_available=semantic.available,
        prompt_version=prompt_version,
        model_used=model_used,
    )

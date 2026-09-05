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
    # Matching Engine V2 (audit item G) — see JobMatchResult for the full
    # rationale. `raw_fit_score` is the pre-cap weighted average;
    # `overall_score` above is what actually drives the decision.
    raw_fit_score: int = 0
    risk_flags: list[str] = field(default_factory=list)
    specific_matched_count: int = 0


def _blend(deterministic_score: int, semantic_score: int, weight: float) -> int:
    return round(deterministic_score * (1 - weight) + semantic_score * weight)


# Audit item G: a job with a hard stop or a clearly incompatible role
# family must never DISPLAY as an apparently excellent numeric match, even
# though neither condition disqualifies it outright on its own (an
# incompatible role family is deliberately never a hard stop by itself —
# see job_agent.matching.deterministic._role_alignment). These caps only
# ever LOWER the score, never raise it, and `raw_fit_score` always keeps
# the uncapped number around so the underlying evidence is never hidden.
_ROLE_FAMILY_MISMATCH_CAP = 45
_HARD_STOP_CAP = 50
_EXCLUDED_CAP = 20


def _apply_score_caps(raw_score: int, deterministic: DeterministicMatch) -> int:
    cap = 100
    if "role_family_mismatch" in deterministic.risk_flags:
        cap = min(cap, _ROLE_FAMILY_MISMATCH_CAP)
    if deterministic.hard_stop_reasons:
        cap = min(cap, _HARD_STOP_CAP)
    if deterministic.excluded_reasons:
        cap = min(cap, _EXCLUDED_CAP)
    return min(raw_score, cap)


def _explain_requirements(deterministic: DeterministicMatch) -> str:
    parts = []
    if deterministic.matched_requirements:
        parts.append(
            "Matched core requirements: "
            + ", ".join(deterministic.matched_requirements)
            + f" ({len(deterministic.matched_requirements)})."
        )
    if deterministic.missing_requirements:
        parts.append(
            "Missing/unconfirmed requirements: "
            + ", ".join(deterministic.missing_requirements)
            + f" ({len(deterministic.missing_requirements)})."
        )
    return " ".join(parts)


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

    raw_fit_score = round(
        sub_scores["skills_match"] * weights.skills
        + sub_scores["experience_match"] * weights.experience
        + sub_scores["role_match"] * weights.role_alignment
        + sub_scores["project_match"] * weights.projects
        + sub_scores["education_match"] * weights.education
        + sub_scores["location_match"] * weights.location
        + sub_scores["seniority_match"] * weights.seniority
        + sub_scores["eligibility_match"] * weights.eligibility
    )
    raw_fit_score = max(0, min(100, raw_fit_score))
    overall_score = _apply_score_caps(raw_fit_score, deterministic)

    requirements_note = _explain_requirements(deterministic)
    if requirements_note:
        reasoning_parts.append(requirements_note)
    if deterministic.risk_flags:
        reasoning_parts.append(f"Risk flags: {', '.join(deterministic.risk_flags)}.")
    if overall_score != raw_fit_score:
        reasoning_parts.append(
            f"Raw fit score {raw_fit_score} capped to {overall_score} due to the risk "
            "flags/hard stops above — the number shown reflects that risk, not just "
            "the weighted sub-scores."
        )

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
        raw_fit_score=raw_fit_score,
        risk_flags=list(deterministic.risk_flags),
        specific_matched_count=deterministic.specific_matched_count,
    )

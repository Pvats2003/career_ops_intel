from __future__ import annotations

from job_agent.config.models import ScoringWeights
from job_agent.matching.deterministic import DeterministicMatch
from job_agent.matching.scoring import combine_match
from job_agent.matching.semantic import SemanticMatchResult, SemanticOutcome

WEIGHTS = ScoringWeights(
    skills=0.25,
    experience=0.20,
    role_alignment=0.20,
    projects=0.10,
    education=0.10,
    location=0.05,
    seniority=0.05,
    eligibility=0.05,
)


def _det(**overrides) -> DeterministicMatch:
    defaults = dict(
        skills_match=60,
        experience_match=60,
        role_match=60,
        project_match=60,
        education_match=60,
        location_match=60,
        seniority_match=60,
        eligibility_match=60,
    )
    defaults.update(overrides)
    return DeterministicMatch(**defaults)


def test_combine_match_deterministic_only_uses_deterministic_scores():
    det = _det(skills_match=80, role_match=40)
    semantic = SemanticOutcome(available=False, unavailable_reason="no key")
    scored = combine_match(det, semantic, weights=WEIGHTS, semantic_blend_weight=0.4)
    assert scored.role_match == 40
    assert scored.skills_match == 80
    assert scored.semantic_available is False
    assert any("unavailable" in c for c in scored.concerns)


def test_combine_match_blends_semantic_for_refinable_dimensions():
    det = _det(role_match=40, experience_match=40, project_match=40)
    semantic_result = SemanticMatchResult(
        role_alignment_score=100,
        experience_similarity_score=100,
        project_relevance_score=100,
        reasoning="great fit",
    )
    semantic = SemanticOutcome(available=True, result=semantic_result)
    scored = combine_match(det, semantic, weights=WEIGHTS, semantic_blend_weight=0.5)
    # 40 * 0.5 + 100 * 0.5 = 70
    assert scored.role_match == 70
    assert scored.experience_match == 70
    assert scored.project_match == 70
    assert scored.semantic_available is True


def test_combine_match_never_blends_non_refinable_dimensions():
    det = _det(
        skills_match=30, education_match=30, location_match=30,
        seniority_match=30, eligibility_match=30,
    )
    semantic_result = SemanticMatchResult(
        role_alignment_score=100, experience_similarity_score=100, project_relevance_score=100,
        reasoning="x",
    )
    semantic = SemanticOutcome(available=True, result=semantic_result)
    scored = combine_match(det, semantic, weights=WEIGHTS, semantic_blend_weight=0.9)
    assert scored.skills_match == 30
    assert scored.education_match == 30
    assert scored.location_match == 30
    assert scored.seniority_match == 30
    assert scored.eligibility_match == 30


def test_combine_match_dedups_concerns_and_missing():
    det = _det(missing_requirements=["SQL"], concerns=["dup concern"])
    semantic_result = SemanticMatchResult(
        role_alignment_score=50, experience_similarity_score=50, project_relevance_score=50,
        additional_missing_requirements=("SQL", "MBA"),
        additional_concerns=("dup concern", "new concern"),
        reasoning="x",
    )
    semantic = SemanticOutcome(available=True, result=semantic_result)
    scored = combine_match(det, semantic, weights=WEIGHTS, semantic_blend_weight=0.5)
    assert scored.missing_requirements.count("SQL") == 1
    assert "MBA" in scored.missing_requirements
    assert scored.concerns.count("dup concern") == 1
    assert "new concern" in scored.concerns


def test_combine_match_overall_score_respects_weights():
    det = _det(**{f: 100 for f in (
        "skills_match", "experience_match", "role_match", "project_match",
        "education_match", "location_match", "seniority_match", "eligibility_match",
    )})
    semantic = SemanticOutcome(available=False, unavailable_reason="skipped")
    scored = combine_match(det, semantic, weights=WEIGHTS, semantic_blend_weight=0.4)
    assert scored.overall_score == 100

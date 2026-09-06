from __future__ import annotations

from job_agent.config.models import MatchingThresholds
from job_agent.matching.decision import decide, finalize
from job_agent.matching.schema import Decision
from job_agent.matching.scoring import ScoredMatch

THRESHOLDS = MatchingThresholds(
    auto_apply_threshold=90, review_threshold=80, save_threshold=70, semantic_blend_weight=0.4
)


def _scored(**overrides) -> ScoredMatch:
    defaults = dict(
        overall_score=50,
        skills_match=50, experience_match=50, role_match=50, project_match=50,
        education_match=50, location_match=50, seniority_match=50, eligibility_match=50,
        semantic_available=True,
    )
    defaults.update(overrides)
    return ScoredMatch(**defaults)


def test_apply_above_auto_threshold_with_semantic():
    scored = _scored(overall_score=95, semantic_available=True)
    assert decide(scored, THRESHOLDS) == Decision.APPLY


def test_capped_to_review_without_high_confidence_evidence_even_above_auto_threshold():
    """Matching Engine V2 (audit item H) rewrote WHY this caps to REVIEW.
    The old rule was "no semantic call was made -> always REVIEW,
    regardless of evidence" — which would have made APPLY permanently
    unreachable for a deterministic-only deployment (production has no
    LLM configured at all). The new rule instead looks at the actual
    deterministic evidence: role_match=50/specific_matched_count=0 here
    is genuinely ambiguous (no clear primary-tier role-family match, no
    confirmed domain-specific skill), so it stays capped to REVIEW on
    the merits — not because semantic didn't run. See
    tests/unit/test_matching_v2.py's test_23/23b/23c for the
    deterministic-only-CAN-reach-APPLY side of this same change."""
    scored = _scored(overall_score=95, semantic_available=False, specific_matched_count=0)
    assert decide(scored, THRESHOLDS) == Decision.REVIEW


def test_review_band():
    scored = _scored(overall_score=85)
    assert decide(scored, THRESHOLDS) == Decision.REVIEW


def test_save_band():
    scored = _scored(overall_score=75)
    assert decide(scored, THRESHOLDS) == Decision.SAVE


def test_skip_below_save_threshold():
    scored = _scored(overall_score=50)
    assert decide(scored, THRESHOLDS) == Decision.SKIP


def test_hard_stop_overrides_high_score():
    scored = _scored(overall_score=99, hard_stop_reasons=["unknown_work_authorization"])
    assert decide(scored, THRESHOLDS) == Decision.HUMAN_REQUIRED


def test_excluded_overrides_everything_including_hard_stop():
    scored = _scored(
        overall_score=99,
        hard_stop_reasons=["unknown_work_authorization"],
        excluded_reasons=["excluded_role:Software Engineer"],
    )
    assert decide(scored, THRESHOLDS) == Decision.SKIP


def test_finalize_produces_valid_job_match_result():
    scored = _scored(overall_score=95, semantic_available=True)
    result = finalize(scored, THRESHOLDS)
    assert result.decision == Decision.APPLY
    assert result.overall_score == 95

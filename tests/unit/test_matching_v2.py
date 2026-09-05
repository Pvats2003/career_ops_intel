"""Matching Engine V2 — forensic false-positive audit regression suite.

Every test here is one of the 25 items enumerated in the audit's Phase 2
test plan. Uses the REAL candidate profile/config (see `real_profile`/
`real_config` in tests/conftest.py) exactly like test_matching_deterministic.py
already does — this candidate's real skills/projects/target roles are the
actual data the false-positive bug was found against, and are what proves
(or disproves) the fix.
"""

from __future__ import annotations

from job_agent.config.models import MatchingThresholds, ScoringWeights
from job_agent.matching.decision import decide, finalize
from job_agent.matching.deterministic import JobText, compute_deterministic_match
from job_agent.matching.role_family import RoleFamily, classify_role_family
from job_agent.matching.schema import Decision
from job_agent.matching.scoring import ScoredMatch, combine_match
from job_agent.matching.semantic import SemanticOutcome

# Used only by the standalone ScoredMatch-level tests (23-24) that don't
# go through real_config at all. Every end-to-end test below (1-19, 25)
# uses `real_config.automation.matching`/`.scoring_weights` directly, so
# it's always exercising the SAME thresholds actually shipped in
# config/automation.yaml — no separate, driftable copy of the numbers.
THRESHOLDS = MatchingThresholds(
    auto_apply_threshold=85, review_threshold=65, save_threshold=50, semantic_blend_weight=0.4
)
WEIGHTS = ScoringWeights(
    skills=0.25, experience=0.20, role_alignment=0.20, projects=0.10,
    education=0.10, location=0.05, seniority=0.05, eligibility=0.05,
)
_NO_SEMANTIC = SemanticOutcome(available=False, unavailable_reason="no key")


def _job(**overrides) -> JobText:
    defaults = dict(title="Associate Product Manager", company="Acme Inc")
    defaults.update(overrides)
    return JobText(**defaults)


def _match(profile, profile_cfg, job: JobText, config=None):
    det = compute_deterministic_match(profile, profile_cfg, job)
    weights = config.automation.scoring_weights if config is not None else WEIGHTS
    blend = config.automation.matching.semantic_blend_weight if config is not None else 0.4
    thresholds = config.automation.matching if config is not None else THRESHOLDS
    scored = combine_match(det, _NO_SEMANTIC, weights=weights, semantic_blend_weight=blend)
    result = finalize(scored, thresholds)
    return det, scored, result


# --------------------------------------------------------------------------
# 1-4: false-positive engineering roles (the audit's core finding)
# --------------------------------------------------------------------------


def test_1_gnc_engineer_false_positive_fixed(real_profile, real_config):
    """The exact production incident: a Senior GNC Engineer posting used
    to score skills=100/project=100 purely from incidental Python/API/
    cross-functional overlap. Reproduces the real reported sub-scores
    (100/65/35/100/55/40/15/80, overall 67%) as the BEFORE state."""
    job = _job(
        title="Senior GNC Engineer",
        company="TYTAN Technologies GmbH",
        description=(
            "Design control algorithms for our launch vehicle. Write flight "
            "software in Python and C++, expose telemetry via internal APIs, "
            "and work cross-functionally with propulsion, avionics, and "
            "structures. Requires deep expertise in control theory, Kalman "
            "filtering, orbital mechanics, and MATLAB/Simulink."
        ),
        location="Munich, Germany", remote_type=None,
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.skills_match <= 60, "generic Python/API overlap must not read as strong skill fit"
    assert det.project_match <= 40
    assert det.specific_matched_count == 0
    assert "role_family_mismatch" in det.risk_flags
    assert result.overall_score < 50, "a hard-stopped, role-mismatched job must not score as strong"
    assert result.decision in (Decision.HUMAN_REQUIRED, Decision.SKIP)


def test_2_structural_engineer_false_positive_fixed(real_profile, real_config):
    job = _job(
        title="Senior Structural Engineer", company="Aeroframe Dynamics",
        description=(
            "Perform finite-element analysis (FEA) on composite airframes "
            "using Nastran/Patran, review stress reports, and coordinate "
            "cross-functionally with manufacturing using our internal "
            "API-driven PLM system. 8+ years in aerospace structures required."
        ),
        location="Seattle, WA", remote_type=None,
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.skills_match <= 60
    assert det.specific_matched_count == 0
    assert "role_family_mismatch" in det.risk_flags
    assert result.overall_score < 55


def test_3_devops_false_positive_fixed(real_profile, real_config):
    job = _job(
        title="DevOps Engineer", company="Cloudspire",
        description=(
            "Manage our cloud infrastructure, build CI/CD pipelines, and "
            "support engineering teams with API-driven tooling in Python. "
            "5+ years experience required."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.project_match <= 40, "Python-only overlap must not manufacture project relevance"
    assert "role_family_mismatch" in det.risk_flags
    assert result.overall_score < 55


def test_4_embedded_engineer_false_positive_fixed(real_profile, real_config):
    job = _job(
        title="Embedded Systems Engineer", company="Kinetix Robotics",
        description=(
            "Write firmware in C/C++ for robotics controllers, integrate "
            "sensor APIs, and use Python for test tooling. 5+ years embedded "
            "systems experience required."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.skills_match <= 60
    assert "role_family_mismatch" in det.risk_flags
    assert "experience_gap_material" in det.hard_stop_reasons
    assert result.overall_score < 55
    assert result.decision == Decision.HUMAN_REQUIRED


# --------------------------------------------------------------------------
# 5-7: skill/requirement coverage model
# --------------------------------------------------------------------------


def test_5_unrelated_job_zero_relevant_vocabulary(real_profile, real_config):
    job = _job(
        title="Line Cook", company="Amber & Rye",
        description="Must be able to work nights and weekends in a busy kitchen.",
        location="Chicago, IL", remote_type=None,
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.skills_match == 55  # genuinely no evidence either way
    assert "role_family_mismatch" in det.risk_flags
    assert result.overall_score < 55


def test_6_generic_python_api_overlap_capped(real_profile, real_config):
    """Two generic-only keyword matches must never alone justify a strong
    skill score — the core mechanism behind the false positives above."""
    job = _job(description="We use Python and expose a public API.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.specific_matched_count == 0
    assert result.skills_match <= 60


def test_7_broad_requirements_only_two_generic_matches(real_profile, real_config):
    """Audit item C's own example: 7 requirements stated, candidate only
    overlaps on the 2 generic ones — must score far below 100%."""
    job = _job(
        description=(
            "Requires Python, API integration experience, SQL, Power BI, "
            "financial modeling, stakeholder analysis, and requirements "
            "gathering."
        )
    )
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.specific_matched_count == 0
    assert result.skills_match < 30


# --------------------------------------------------------------------------
# 8-13: missing information / hard-stop redesign
# --------------------------------------------------------------------------


def test_8_missing_experience_requirement_is_neutral_not_boosted(real_profile, real_config):
    job = _job(description="A great opportunity for the right candidate.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.experience_match == 55  # NOT 65


def test_9_unknown_eligibility_is_neutral_not_positive(real_profile, real_config):
    job = _job(description="A wonderful opportunity to grow your career.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.eligibility_match == 55  # NOT 80
    assert "eligibility_uncertain" in result.risk_flags
    assert "unknown_work_authorization" not in result.hard_stop_reasons


def test_10_explicit_sponsorship_requirement_hard_stop_preserved(real_profile, real_config):
    job = _job(description="Must be authorized to work in the United States without sponsorship.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "unknown_work_authorization" in result.hard_stop_reasons
    assert result.eligibility_match < 50


def test_11_seniority_mismatch_caps_score_even_with_matched_role_family(real_profile, real_config):
    """Audit item G: a hard-stopped job must not DISPLAY as an apparently
    excellent numeric match even though its role family genuinely matches."""
    job = _job(
        title="Senior Business Analyst", description="SQL, Excel, stakeholder communication."
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match == 90  # role family genuinely matched (primary tier)
    assert "seniority_mismatch" in det.hard_stop_reasons
    assert result.overall_score <= 50, "hard-stop cap must apply even to a role-matched job"
    assert result.decision == Decision.HUMAN_REQUIRED


def test_12_missing_degree_requirement_hard_stop_preserved(real_profile, real_config):
    job = _job(description="MBA required for this role.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "required_degree_missing" in result.hard_stop_reasons
    assert result.education_match < 50


def test_13_location_mismatch_preserved(real_profile, real_config):
    job = _job(location="Berlin, Germany", remote_type=None)
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.location_match == 40


# --------------------------------------------------------------------------
# 14-19: genuine strong matches must still score well
# --------------------------------------------------------------------------


def test_14_genuine_business_analyst_strong_match(real_profile, real_config):
    job = _job(
        title="Business Analyst",
        description=(
            "Business Analyst to support stakeholder communication, process documentation, "
            "business analysis, and KPI reporting across our operations teams, using Excel and "
            "Google Sheets for ad hoc analysis. Bachelor's degree required. Entry-level "
            "candidates welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match == 90
    assert result.decision not in (Decision.SKIP, Decision.HUMAN_REQUIRED)


def test_15_genuine_product_analyst_strong_match(real_profile, real_config):
    job = _job(
        title="Product Analyst",
        description=(
            "Product Analyst role: draft PRDs, run sprint planning and backlog grooming with "
            "the engineering team, use MoSCoW to prioritize the roadmap, and support user "
            "research. Bachelor's degree required. New grads welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match == 90
    assert result.decision not in (Decision.SKIP, Decision.HUMAN_REQUIRED)


def test_16_genuine_operations_analyst_strong_match(real_profile, real_config):
    job = _job(
        title="Operations Analyst",
        description=(
            "Operations Analyst -- own process documentation, KPI and OKR reporting, "
            "stakeholder management, and cross-functional coordination between teams. "
            "Bachelor's degree required. Entry-level welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match >= 72
    assert result.decision not in (Decision.SKIP, Decision.HUMAN_REQUIRED)


def test_17_genuine_marketing_operations_strong_match(real_profile, real_config):
    job = _job(
        title="Marketing Operations Analyst",
        description=(
            "Marketing Operations Analyst -- run market research and competitive analysis, "
            "build KPI dashboards, and coordinate cross-functionally with growth and sales. "
            "Bachelor's degree required. New grads welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match >= 72
    assert result.decision not in (Decision.SKIP, Decision.HUMAN_REQUIRED)


def test_18_genuine_product_operations_strong_match(real_profile, real_config):
    job = _job(
        title="Product Operations Analyst",
        description=(
            "Product Operations Analyst -- own cross-functional process documentation, "
            "KPI/OKR tracking, and stakeholder management across product and support teams. "
            "Bachelor's degree required. Entry-level welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match >= 72
    assert result.decision not in (Decision.SKIP, Decision.HUMAN_REQUIRED)


def test_19_genuine_entry_level_associate_target_role(real_profile, real_config):
    job = _job(
        title="Associate Product Manager",
        description=(
            "Associate Product Manager -- draft PRDs, run sprint planning and backlog "
            "grooming, prioritize using MoSCoW, and support user research and usability "
            "research. Bachelor's degree required. New grads and entry-level candidates welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert det.role_match == 90
    assert det.seniority_match == 90  # "entry-level" boosts, doesn't just avoid penalty
    assert result.decision != Decision.SKIP


# --------------------------------------------------------------------------
# 20: role-family classification
# --------------------------------------------------------------------------


def test_20_role_family_classification_distinguishes_engineer_titles():
    """The audit's explicit warning: not every "...Engineer" title is
    Software/Hardware engineering — a Business Systems Engineer, Solutions
    Engineer, or Analytics Engineer need different treatment."""
    assert classify_role_family("Business Systems Engineer").family == RoleFamily.BUSINESS_ANALYSIS
    assert classify_role_family("Analytics Engineer").family == RoleFamily.DATA_ANALYTICS
    assert classify_role_family("Solutions Consultant").family == RoleFamily.SALES
    assert (
        classify_role_family("Senior GNC Engineer").family
        == RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING
    )
    assert classify_role_family("Software Engineer").family == RoleFamily.SOFTWARE_ENGINEERING
    assert classify_role_family("Site Reliability Engineer").family == RoleFamily.DEVOPS_SRE
    # An unfamiliar engineering title must never be guessed into a bucket —
    # OTHER_UNKNOWN, not silently "Software Engineering".
    assert classify_role_family("Chemical Process Engineer").family == RoleFamily.OTHER_UNKNOWN


# --------------------------------------------------------------------------
# 21-22: dashboard ranking + metric semantics (API-level)
# --------------------------------------------------------------------------
# See tests/unit/test_web_api.py::test_dashboard_top_opportunities_never_shows_skip
# and ::test_dashboard_metrics_distinguish_scored_from_qualified for the
# full API-level regression tests (they need the FastAPI test client /
# seeded DB fixtures already defined there, not duplicated here).


# --------------------------------------------------------------------------
# 23-24: deterministic-only APPLY eligibility / LLM path stays compatible
# --------------------------------------------------------------------------


def _scored(**overrides) -> ScoredMatch:
    defaults = dict(
        overall_score=95, raw_fit_score=95,
        skills_match=90, experience_match=90, role_match=50, project_match=90,
        education_match=90, location_match=90, seniority_match=90, eligibility_match=90,
        semantic_available=False, specific_matched_count=0, risk_flags=[],
    )
    defaults.update(overrides)
    return ScoredMatch(**defaults)


def test_23_deterministic_only_can_reach_apply_with_high_confidence_evidence():
    """Audit item H: 'no LLM does not mean never APPLY' — real,
    strong deterministic-only evidence must be able to unlock APPLY on
    its own, without ever having called an LLM."""
    scored = _scored(role_match=90, specific_matched_count=3, risk_flags=[])
    assert decide(scored, THRESHOLDS) == Decision.APPLY


def test_23b_deterministic_only_proof_of_the_old_bug():
    """Documents the OLD (now-removed) rule this replaces: semantic
    availability used to be the ONLY way to reach APPLY, capping every
    deterministic-only deployment at REVIEW no matter how strong the
    evidence — meaningful here because production has no LLM configured
    at all, so APPLY would have been permanently unreachable."""
    scored = _scored(
        role_match=90, specific_matched_count=3, risk_flags=[], semantic_available=False
    )
    # Under the OLD rule this would have been REVIEW solely because
    # semantic_available is False -- the new rule looks at the evidence
    # instead and correctly reaches APPLY (see test_23 above).
    assert decide(scored, THRESHOLDS) != Decision.REVIEW


def test_23c_deterministic_only_stays_capped_without_sufficient_confidence():
    """The gate is real, not a rubber stamp: an ambiguous/unconfirmed role
    match must still be capped to REVIEW even at a high overall score."""
    scored = _scored(role_match=50, specific_matched_count=0, risk_flags=[])
    assert decide(scored, THRESHOLDS) == Decision.REVIEW


def test_24_llm_enabled_path_remains_a_sufficient_independent_route_to_apply():
    """Semantic confirmation is still a fully independent, sufficient path
    to APPLY — it was never meant to become a requirement, only to remain
    an optional additional confirmation."""
    scored = _scored(role_match=50, specific_matched_count=0, semantic_available=True)
    assert decide(scored, THRESHOLDS) == Decision.APPLY


# --------------------------------------------------------------------------
# 25: explainability
# --------------------------------------------------------------------------


def test_25_reasoning_names_matched_and_missing_requirements(real_profile, real_config):
    job = _job(
        title="Business Analyst",
        description="Requires stakeholder communication, process documentation, and Tableau.",
    )
    _, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert "Matched core requirements:" in result.reasoning
    assert "stakeholder communication" in result.reasoning
    assert "Missing/unconfirmed requirements:" in result.reasoning
    assert "Tableau" in result.reasoning


def test_25b_reasoning_explains_a_score_cap(real_profile, real_config):
    """A job whose OTHER components (skills via generic overlap, project
    fallback, education, location, seniority) are strong enough to raise
    the raw weighted average comfortably above the role-family-mismatch
    cap — proving the cap actually engages and is explained, not just
    present in the (already-low) common case."""
    job = _job(
        title="DevOps Engineer",
        description=(
            "Support our engineering team using Python, SQL, and internal APIs, with strong "
            "communication and documentation skills. Bachelor's degree required. Entry-level "
            "candidates and new grads welcome."
        ),
        remote_type="remote",
    )
    det, scored, result = _match(real_profile, real_config.profile, job, real_config)
    assert "role_family_mismatch" in det.risk_flags
    assert result.overall_score < result.raw_fit_score
    assert "capped" in result.reasoning
    assert "Risk flags:" in result.reasoning

"""Career path discovery (job_agent.candidate.career_paths)."""

from __future__ import annotations

from job_agent.candidate.career_paths import discover_career_paths
from job_agent.candidate.schema import (
    CandidateProfile,
    ExperienceEntry,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    SkillFact,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)


def _fact(value: str) -> Fact[str]:
    return Fact[str](value=value, source="test", confidence=1.0, verified=True)


def _skill(name: str, category: str = "technical") -> SkillFact:
    return SkillFact(
        name=name, category=category, evidence_level="HAS",
        source="test", confidence=1.0, verified=True,
    )


def _profile(**overrides) -> CandidateProfile:
    unknown = Fact.unknown(source="test")
    base = dict(
        identity_name=_fact("Test Candidate"),
        identity_current_location=_fact("Remote"),
        contact_email=_fact("test@example.invalid"),
        contact_phone=_fact("+1-555-0100"),
        contact_linkedin=_fact("https://linkedin.com/in/test"),
        target_roles=TargetRoles(),
        skills=(),
        experience=(),
        education=(),
        work_preferences=WorkPreferences(
            remote=unknown, willing_to_relocate=unknown, notice_period=unknown
        ),
        location_preferences=LocationPreferences(
            current_location=_fact("Remote"), open_to_countries=unknown
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown, minimum_annual=unknown, target_annual=unknown, negotiable=unknown
        ),
        visa_information=VisaInformation(
            nationality=unknown, requires_sponsorship_us=unknown,
            requires_sponsorship_uk=unknown, requires_sponsorship_eu=unknown,
            requires_sponsorship_other=unknown,
        ),
    )
    base.update(overrides)
    return CandidateProfile(**base)


def test_empty_profile_produces_no_paths():
    assert discover_career_paths(_profile()) == []


def test_path_requires_real_evidence_not_fabricated():
    profile = _profile(skills=(_skill("SQL"), _skill("Excel")))
    results = discover_career_paths(profile)
    assert results
    for result in results:
        assert result.evidence, f"{result.label} has no evidence but was returned"


def test_stated_primary_target_role_outranks_pure_skill_overlap():
    profile = _profile(
        target_roles=TargetRoles(primary=("Product Analyst",)),
        skills=(_skill("SQL"),),
    )
    results = discover_career_paths(profile)
    labels = [r.label for r in results]
    assert "Product Management" in labels
    pm = next(r for r in results if r.label == "Product Management")
    assert pm.recommended_priority == "HIGH"


def test_missing_skills_never_overlap_relevant_skills():
    profile = _profile(skills=(_skill("Python"), _skill("React")))
    results = discover_career_paths(profile)
    for result in results:
        assert set(result.relevant_skills).isdisjoint(set(result.missing_skills))


def test_experience_title_counts_as_evidence():
    profile = _profile(
        experience=(
            ExperienceEntry(
                title="Business Analyst", company="Acme", start_date="2023-01",
                end_date="2024-01", source="test",
            ),
        ),
    )
    results = discover_career_paths(profile)
    labels = [r.label for r in results]
    assert "Business Analysis" in labels


def test_top_three_are_high_priority_rest_lower():
    profile = _profile(
        skills=(
            _skill("SQL"), _skill("Excel"), _skill("Python"), _skill("React"),
            _skill("Node.js"), _skill("TypeScript"), _skill("Figma"),
            _skill("stakeholder management"), _skill("process documentation"),
            _skill("KPI"), _skill("market research"),
        ),
    )
    results = discover_career_paths(profile)
    assert len(results) >= 4
    priorities = [r.recommended_priority for r in results]
    assert priorities[:3] == ["HIGH", "HIGH", "HIGH"]
    assert priorities[0] != "LOW"


def test_results_sorted_by_fit_score_descending():
    profile = _profile(
        skills=(_skill("SQL"), _skill("Excel"), _skill("Python"), _skill("Figma")),
    )
    results = discover_career_paths(profile)
    scores = [r.fit_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_max_results_is_respected():
    profile = _profile(
        skills=(
            _skill("SQL"), _skill("Excel"), _skill("Python"), _skill("React"),
            _skill("Figma"), _skill("KPI"), _skill("market research"),
        ),
    )
    results = discover_career_paths(profile, max_results=2)
    assert len(results) <= 2

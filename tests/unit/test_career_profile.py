"""Career Profile (job_agent.candidate.career_profile) — CAREER OS FINAL
GOD MODE Part 2.4."""

from __future__ import annotations

from job_agent.candidate.career_paths import CareerPathResult
from job_agent.candidate.career_profile import build_career_profile
from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)


def _fact(value: str) -> Fact[str]:
    return Fact[str](value=value, source="test", confidence=1.0, verified=True)


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


def _path(**overrides) -> CareerPathResult:
    base = dict(
        label="Product Operations", fit_score=90, evidence=("evidence",),
        relevant_skills=("SQL", "Excel"), relevant_experience=(), missing_skills=("Python",),
        typical_titles=(), career_upside="High", recommended_priority="HIGH",
    )
    base.update(overrides)
    return CareerPathResult(**base)


def test_empty_career_paths_yields_no_direction_but_still_locations():
    profile = _profile(
        location_preferences=LocationPreferences(
            current_location=_fact("Remote"), open_to_countries=Fact.unknown(source="test"),
            preferred_locations=("Singapore", "India"),
        )
    )
    result = build_career_profile(profile, [])
    assert result.primary_direction is None
    assert result.strengths == ()
    assert result.best_locations == ("Singapore", "India")


def test_primary_direction_uses_top_path_label():
    profile = _profile()
    result = build_career_profile(profile, [_path(label="Product Operations", fit_score=90)])
    assert result.primary_direction == "Product Operations"


def test_primary_direction_combines_close_second_path():
    profile = _profile()
    paths = [
        _path(label="Product Operations", fit_score=90),
        _path(label="AI Operations", fit_score=88),
    ]
    result = build_career_profile(profile, paths)
    assert result.primary_direction == "Product Operations / AI Operations"


def test_primary_direction_excludes_distant_second_path():
    profile = _profile()
    paths = [
        _path(label="Product Operations", fit_score=90),
        _path(label="Data Analytics", fit_score=50),
    ]
    result = build_career_profile(profile, paths)
    assert result.primary_direction == "Product Operations"


def test_strengths_ranked_by_cross_path_frequency():
    profile = _profile()
    paths = [
        _path(label="A", relevant_skills=("SQL", "Excel")),
        _path(label="B", relevant_skills=("SQL", "Automation")),
    ]
    result = build_career_profile(profile, paths)
    assert result.strengths[0] == "SQL"  # appears in both paths


def test_skill_gaps_pooled_from_top_paths():
    profile = _profile()
    paths = [
        _path(label="A", missing_skills=("Python",)),
        _path(label="B", missing_skills=("Python", "R")),
    ]
    result = build_career_profile(profile, paths)
    assert "Python" in result.skill_gaps


def test_growing_area_is_the_emerging_upside_path():
    profile = _profile()
    paths = [
        _path(label="Product Operations", fit_score=90, career_upside="High"),
        _path(label="AI Product Workflows", fit_score=70, career_upside="Emerging"),
    ]
    result = build_career_profile(profile, paths)
    assert result.growing_area == "AI Product Workflows"


def test_no_emerging_path_yields_no_growing_area():
    profile = _profile()
    paths = [_path(label="Product Operations", career_upside="High")]
    result = build_career_profile(profile, paths)
    assert result.growing_area is None


def test_best_locations_falls_back_to_verified_current_location():
    profile = _profile(
        location_preferences=LocationPreferences(
            current_location=_fact("Singapore"), open_to_countries=Fact.unknown(source="test"),
        )
    )
    result = build_career_profile(profile, [])
    assert result.best_locations == ("Singapore",)


def test_best_locations_empty_when_nothing_known():
    profile = _profile(
        location_preferences=LocationPreferences(
            current_location=Fact.unknown(source="test"),
            open_to_countries=Fact.unknown(source="test"),
        )
    )
    result = build_career_profile(profile, [])
    assert result.best_locations == ()

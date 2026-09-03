"""Search query portfolio generation (job_agent.jobs.query_generator)."""

from __future__ import annotations

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
from job_agent.jobs.query_generator import generate_search_queries


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
        target_roles=TargetRoles(
            primary=("Product Operations Analyst",),
            secondary=("Business Operations",),
            exploratory=("AI Operations",),
        ),
        skills=(
            SkillFact(
                name="Automation", category="technical", evidence_level="HAS",
                source="test", confidence=1.0, verified=True,
            ),
            SkillFact(
                name="Communication", category="soft", evidence_level="HAS",
                source="test", confidence=1.0, verified=True,
            ),
        ),
        experience=(
            ExperienceEntry(
                title="Operations Intern", company="Acme", start_date="2024-01",
                end_date="2024-06", source="test",
            ),
        ),
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


def test_core_roles_come_from_target_roles_primary():
    portfolio = generate_search_queries(_profile())
    assert "Product Operations Analyst" in portfolio.core_roles


def test_adjacent_roles_come_from_target_roles_secondary():
    portfolio = generate_search_queries(_profile())
    assert "Business Operations" in portfolio.adjacent_roles


def test_transferable_roles_combine_technical_skills_with_role_suffixes():
    portfolio = generate_search_queries(_profile())
    assert any(q.startswith("Automation ") for q in portfolio.transferable_skill_roles)


def test_soft_skills_never_become_transferable_role_queries():
    portfolio = generate_search_queries(_profile())
    assert not any("Communication" in q for q in portfolio.transferable_skill_roles)


def test_emerging_roles_include_exploratory_and_past_titles():
    portfolio = generate_search_queries(_profile())
    assert "AI Operations" in portfolio.emerging_roles
    assert "Operations Intern" in portfolio.emerging_roles


def test_all_queries_deduplicates_across_buckets():
    portfolio = generate_search_queries(_profile())
    lowered = [q.lower() for q in portfolio.all_queries]
    assert len(lowered) == len(set(lowered))


def test_never_fabricates_a_role_not_in_the_profile():
    """Only roles/skills/titles that are actually present in the profile
    should ever appear — no hardcoded example titles leak in."""
    portfolio = generate_search_queries(_profile())
    assert "Chief Executive Officer" not in portfolio.all_queries
    assert "Software Engineer" not in portfolio.all_queries


def test_empty_profile_produces_empty_portfolio_not_a_crash():
    empty = _profile(
        target_roles=TargetRoles(), skills=(), experience=(),
    )
    portfolio = generate_search_queries(empty)
    assert portfolio.all_queries == ()

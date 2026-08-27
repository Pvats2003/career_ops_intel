from __future__ import annotations

from job_agent.matching.deterministic import JobText, compute_deterministic_match


def _job(**overrides) -> JobText:
    defaults = dict(title="Associate Product Manager", company="Acme Inc")
    defaults.update(overrides)
    return JobText(**defaults)


def test_skills_match_finds_fuzzy_evidence(real_profile, real_config):
    job = _job(
        description="Work with SQL and Excel daily. Agile/Scrum experience needed.",
        requirements="Figma for wireframing.",
    )
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.skills_match > 70
    assert "SQL" not in result.missing_requirements


def test_skills_match_flags_genuinely_missing_terms(real_profile, real_config):
    job = _job(description="Must know Tableau and Power BI for this role.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "Tableau" in result.missing_requirements
    assert "Power BI" in result.missing_requirements


def test_skills_match_neutral_when_no_vocabulary_mentioned(real_profile, real_config):
    job = _job(description="A great place to work with amazing people.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.skills_match == 55
    assert result.missing_requirements == []


def test_role_alignment_primary_role(real_profile, real_config):
    job = _job(title="Associate Product Manager")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.role_match == 90
    assert result.excluded_reasons == []


def test_role_alignment_excluded_role(real_profile, real_config):
    job = _job(title="Senior Product Manager")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.excluded_reasons
    assert result.role_match == 0


def test_role_alignment_excluded_company(real_profile, real_config):
    job = _job(title="Product Analyst", company="SomeExcludedCo")
    # Simulate an excluded company by checking the mechanism directly since
    # the shipped config ships an empty excluded_companies list.
    from job_agent.config.models import ProfileConfig

    cfg = real_config.profile.model_copy(
        update={"excluded_companies": ["SomeExcludedCo"]}, deep=True
    )
    assert isinstance(cfg, ProfileConfig)
    result = compute_deterministic_match(real_profile, cfg, job)
    assert any("excluded_company" in r for r in result.excluded_reasons)


def test_education_hard_stop_for_missing_advanced_degree(real_profile, real_config):
    job = _job(description="MBA required for this role.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "required_degree_missing" in result.hard_stop_reasons
    assert result.education_match < 50


def test_education_ok_when_bachelors_required(real_profile, real_config):
    job = _job(description="Bachelor's degree required.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.education_match == 90
    assert "required_degree_missing" not in result.hard_stop_reasons


def test_seniority_hard_stop_for_senior_title(real_profile, real_config):
    job = _job(title="Staff Product Manager")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "seniority_mismatch" in result.hard_stop_reasons
    assert result.seniority_match < 50


def test_seniority_boost_for_junior_keywords(real_profile, real_config):
    job = _job(description="This is an entry-level, new grad friendly role.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.seniority_match == 90


def test_eligibility_hard_stop_when_visa_unknown(real_profile, real_config):
    job = _job(description="Must be authorized to work in the United States without sponsorship.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "unknown_work_authorization" in result.hard_stop_reasons
    assert result.eligibility_match < 50


def test_eligibility_neutral_when_no_sponsorship_language(real_profile, real_config):
    job = _job(description="A wonderful opportunity to grow your career.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert "unknown_work_authorization" not in result.hard_stop_reasons


def test_location_remote_scores_high(real_profile, real_config):
    job = _job(remote_type="remote", location="Remote - Anywhere")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.location_match >= 85


def test_location_matches_current_location(real_profile, real_config):
    job = _job(location="Manipal, Karnataka, India", remote_type="onsite")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.location_match >= 85


def test_experience_gap_flagged(real_profile, real_config):
    job = _job(description="5+ years of experience required.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.experience_match < 50
    assert any("5+ years" in c for c in result.concerns)


def test_experience_no_requirement_stated(real_profile, real_config):
    job = _job(description="A great opportunity for the right candidate.")
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert result.experience_match > 50


def test_multiple_hard_stops_all_survive_aggregation(real_profile, real_config):
    """Independent hard-stop conditions must accumulate, not overwrite each
    other — decision.py needs to see every one of them, not just the last
    sub-check that happened to run."""
    job = _job(
        title="Staff Product Analyst",  # triggers seniority_mismatch, not excluded
        description=(
            "MBA required. Must be authorized to work in the United States "
            "without sponsorship."
        ),
    )
    result = compute_deterministic_match(real_profile, real_config.profile, job)
    assert set(result.hard_stop_reasons) == {
        "required_degree_missing",
        "seniority_mismatch",
        "unknown_work_authorization",
    }
    assert result.excluded_reasons == []

from __future__ import annotations

import pytest

from job_agent.candidate.parser import (
    CandidateParseError,
    parse_achievements,
    parse_candidate_profile,
    parse_education,
    parse_experience,
    parse_profile,
    parse_projects,
    parse_skills,
)
from job_agent.candidate.schema import EvidenceLevel


def test_parse_profile_real_file(real_config):
    fields = parse_profile(real_config.env.candidate_dir / "profile.md")
    assert fields["name"] == "Priyanshu Vats"
    assert fields["email"] == "priyanshu.vats03@gmail.com"


def test_parse_experience_real_file(real_config):
    entries = parse_experience(real_config.env.candidate_dir / "experience.md")
    assert len(entries) == 2
    titles = {e.title for e in entries}
    assert "Operations Management Intern, Field Operations" in titles
    for e in entries:
        assert e.highlights
        assert e.source.endswith("experience.md")


def test_parse_projects_real_file(real_config):
    entries = parse_projects(real_config.env.candidate_dir / "projects.md")
    assert len(entries) == 4
    assert all(p.is_professional_experience is False for p in entries)


def test_parse_skills_real_file(real_config):
    skills = parse_skills(real_config.env.candidate_dir / "skills.md")
    by_name = {s.name: s for s in skills}
    assert by_name["Python"].evidence_level == EvidenceLevel.DEMONSTRATED
    assert by_name["Figma (basic)"].evidence_level == EvidenceLevel.HAS
    # Every skill must carry provenance pointing at skills.md.
    assert all(s.source.endswith("skills.md") for s in skills)
    assert all(s.confidence == 1.0 and s.verified for s in skills)


def test_parse_education_real_file(real_config):
    education, certifications = parse_education(real_config.env.candidate_dir / "education.md")
    assert len(education) == 1
    assert education[0].institution == "MIT Manipal, Karnataka"
    assert len(certifications) == 1
    assert certifications[0].name == "Google UX Design Certificate"


def test_parse_achievements_real_file(real_config):
    achievements = parse_achievements(real_config.env.candidate_dir / "achievements.md")
    assert len(achievements) >= 2
    titles = {a.title for a in achievements}
    assert any("Revels 2025" in t for t in titles)


def test_full_profile_assembly_never_fabricates_preferences(real_config):
    profile = parse_candidate_profile(real_config)
    # Resume never states salary/visa facts -> must stay UNKNOWN, never guessed.
    assert profile.salary_preferences.target_annual.is_unknown
    assert profile.visa_information.nationality.is_unknown
    assert profile.visa_information.is_fully_known is False


def test_full_profile_assembly_identity(real_config):
    profile = parse_candidate_profile(real_config)
    assert profile.identity_name.value == "Priyanshu Vats"
    assert profile.identity_name.verified is True
    assert profile.identity_name.confidence == 1.0


def test_adjacent_skills_never_from_parser_alone_is_valid_but_marked(real_config):
    """No skill in the shipped skills.md may claim MISSING/UNKNOWN — the
    parser itself enforces this via SkillFact validation, so a successful
    parse is already proof; this test asserts the file exercises at least
    one non-HAS evidence level so the distinction is actually meaningful."""
    profile = parse_candidate_profile(real_config)
    levels = {s.evidence_level for s in profile.skills}
    assert EvidenceLevel.DEMONSTRATED in levels
    assert EvidenceLevel.HAS in levels


def test_missing_required_section_raises(tmp_path):
    bad = tmp_path / "profile.md"
    bad.write_text("## Identity\nname: Someone\n")
    with pytest.raises(CandidateParseError):
        parse_profile(bad)


def test_missing_file_raises(tmp_path):
    with pytest.raises(CandidateParseError):
        parse_profile(tmp_path / "does_not_exist.md")


def test_bad_skill_evidence_level_raises(tmp_path):
    bad = tmp_path / "skills.md"
    bad.write_text("## Cat\n- Skill Name :: category :: NOT_A_REAL_LEVEL\n")
    with pytest.raises(CandidateParseError):
        parse_skills(bad)


def test_experience_missing_pipe_raises(tmp_path):
    bad = tmp_path / "experience.md"
    bad.write_text(
        "### Title Without Company Separator\nstart_date: 2024\nend_date: 2024\n- bullet\n"
    )
    with pytest.raises(CandidateParseError):
        parse_experience(bad)

from __future__ import annotations

import pytest

from job_agent.candidate.schema import (
    AchievementEntry,
    CertificationEntry,
    EducationEntry,
    EvidenceLevel,
    ExperienceEntry,
    ProjectEntry,
    SkillFact,
)
from job_agent.resume.extractor import extract_resume_text
from job_agent.resume.validator import validate_profile_against_resume


@pytest.fixture(scope="session")
def resume_text(repo_root):
    return extract_resume_text(repo_root / "candidate" / "resume_master.docx")


def test_real_profile_has_zero_issues(real_profile, resume_text):
    """The single most important test in this module: the actual shipped
    candidate profile must be fully traceable to the actual resume file. A
    failure here means either a real authoring inconsistency (candidate/
    *.md drifted from resume_master.docx) or a validator bug — either way
    it must never be silently ignored."""
    issues = validate_profile_against_resume(real_profile, resume_text)
    assert issues == []


def test_fabricated_experience_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "experience": (
                *real_profile.experience,
                ExperienceEntry(
                    title="Senior Staff Engineer",
                    company="Totally Fake Corp LLC",
                    start_date="2020-01",
                    end_date="2021-01",
                    source="fabricated",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    fields = {i.field for i in issues}
    assert any("experience" in f and "title" in f for f in fields)
    assert any("experience" in f and "company" in f for f in fields)


def test_fabricated_has_skill_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "skills": (
                *real_profile.skills,
                SkillFact(
                    name="Kubernetes Administration",
                    category="technical",
                    evidence_level=EvidenceLevel.HAS,
                    source="fabricated",
                    confidence=1.0,
                    verified=True,
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("Kubernetes Administration" in i.detail for i in issues)


def test_demonstrated_skill_with_unrelated_note_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "skills": (
                *real_profile.skills,
                SkillFact(
                    name="Deep Learning",
                    category="technical",
                    evidence_level=EvidenceLevel.DEMONSTRATED,
                    source="fabricated",
                    confidence=1.0,
                    verified=True,
                    note="trained a transformer model at a company never mentioned anywhere",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("Deep Learning" in i.field for i in issues)


def test_demonstrated_skill_without_note_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "skills": (
                *real_profile.skills,
                SkillFact(
                    name="Unverifiable Skill",
                    category="technical",
                    evidence_level=EvidenceLevel.DEMONSTRATED,
                    source="fabricated",
                    confidence=1.0,
                    verified=True,
                    note=None,
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("no evidence note" in i.detail for i in issues)


def test_fabricated_education_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "education": (
                *real_profile.education,
                EducationEntry(
                    program="PhD in Astrophysics",
                    institution="Fictional University of Nowhere",
                    graduation_date="2030-01",
                    degree_level="phd",
                    source="fabricated",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("institution" in i.field for i in issues)


def test_fabricated_certification_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "certifications": (
                *real_profile.certifications,
                CertificationEntry(
                    name="Certified Underwater Basket Weaving Expert",
                    source="fabricated",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("certifications" in i.field for i in issues)


def test_fabricated_project_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "projects": (
                *real_profile.projects,
                ProjectEntry(
                    name="Interstellar Navigation System",
                    status="Ongoing",
                    project_type="Self-Initiated Product",
                    source="fabricated",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("projects" in i.field for i in issues)


def test_fabricated_achievement_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "achievements": (
                *real_profile.achievements,
                AchievementEntry(
                    title="Won National Robotics Championship 2019",
                    highlights=("Awarded first place among 500 international teams",),
                    source="fabricated",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any("achievements" in i.field for i in issues)


def test_fabricated_identity_is_caught(real_profile, resume_text):
    fabricated = real_profile.model_copy(
        update={
            "identity_name": real_profile.identity_name.model_copy(
                update={"value": "John Q Nobody"}
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert any(i.field == "identity_name" for i in issues)


def test_legitimate_paraphrase_of_real_achievement_passes(real_profile, resume_text):
    """Regression guard: fuzzy matching must tolerate honest paraphrasing of
    a REAL fact (this is what candidate/achievements.md actually does for
    the 'Notable Project Metrics' entries) — it must not force everything
    into a false 'fabrication' bucket just because the wording differs."""
    paraphrased = real_profile.model_copy(
        update={
            "achievements": (
                AchievementEntry(
                    title="Instawork Robotics Labs internship",
                    highlights=(
                        "Produced the South India VLA Field Recording Guide covering 116 "
                        "businesses across 19 categories",
                    ),
                    source="candidate/achievements.md",
                ),
            )
        }
    )
    issues = validate_profile_against_resume(paraphrased, resume_text)
    assert issues == []


def test_adjacent_skill_is_never_checked(real_profile, resume_text):
    """ADJACENT skills are matching-only, never a claim — see rules.yaml
    truth_validation.internal_only. The validator must not flag one just
    because its name doesn't appear verbatim in the resume."""
    fabricated = real_profile.model_copy(
        update={
            "skills": (
                *real_profile.skills,
                SkillFact(
                    name="Something Not In The Resume At All",
                    category="technical",
                    evidence_level=EvidenceLevel.ADJACENT,
                    source="inference",
                    confidence=0.3,
                    verified=False,
                ),
            )
        }
    )
    issues = validate_profile_against_resume(fabricated, resume_text)
    assert issues == []

"""Resume tailoring (job_agent.resume.tailor) — Career OS Phase 9 section 11."""

from __future__ import annotations

from job_agent.candidate.schema import (
    CandidateProfile,
    ExperienceEntry,
    Fact,
    LocationPreferences,
    ProjectEntry,
    SalaryPreferences,
    SkillFact,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.llm.errors import LLMOutputValidationError, LLMUnavailableError
from job_agent.llm.provider import LLMCallMetadata, LLMProvider
from job_agent.resume.tailor import tailor_resume_for_job


def _fact(value: str) -> Fact[str]:
    return Fact[str](value=value, source="test", confidence=1.0, verified=True)


def _skill(name: str, category: str = "technical") -> SkillFact:
    return SkillFact(
        name=name, category=category, evidence_level="HAS",
        source="test", confidence=1.0, verified=True,
    )


def _experience(title: str, company: str, highlights: tuple[str, ...] = ()) -> ExperienceEntry:
    return ExperienceEntry(
        title=title, company=company, start_date="2023-01", end_date="2024-01",
        highlights=highlights, source="test",
    )


def _project(name: str, highlights: tuple[str, ...] = ()) -> ProjectEntry:
    return ProjectEntry(
        name=name, status="completed", project_type="personal",
        highlights=highlights, source="test",
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
        projects=(),
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


def test_deterministic_operation_with_no_llm():
    profile = _profile(
        target_roles=TargetRoles(primary=("Business Analyst",)),
        skills=(_skill("SQL"), _skill("Excel")),
    )
    result = tailor_resume_for_job(
        profile, None, job_title="Business Analyst", job_company="Acme",
        job_description="We need someone strong in SQL and Excel.", job_requirements=None,
    )
    assert result.generated_by == "deterministic"
    assert result.professional_summary
    assert "SQL" in result.relevant_skills


def test_never_fabricates_relevant_skills_beyond_profile():
    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="Looking for Python and Tableau experience.", job_requirements=None,
    )
    assert "Python" not in result.relevant_skills
    assert "Tableau" not in result.relevant_skills


def test_ats_keywords_only_include_skills_the_candidate_actually_has():
    profile = _profile(skills=(_skill("SQL"), _skill("Agile")))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="Must know SQL, Agile, and Tableau.", job_requirements=None,
    )
    assert "SQL" in result.ats_keywords
    assert "Agile" in result.ats_keywords
    assert "Tableau" not in result.ats_keywords


def test_notes_flag_missing_requirements_without_claiming_them():
    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="Must know Tableau.", job_requirements=None,
    )
    assert any("Tableau" in note for note in result.notes)
    assert "Tableau" not in result.relevant_skills


def test_qualified_skill_name_still_counts_as_relevant():
    """Real-world activation audit finding: a candidate's skill is often
    authored with a self-rating qualifier ("Basic SQL", "Figma (basic)")
    rather than the bare term a job posting uses ("SQL", "Figma"). An
    exact-phrase match would wrongly report a real, demonstrated skill as
    "not found in your profile" — the same fuzzy-substring check
    matching.deterministic._find_evidence already uses for match scoring
    must also apply here, or the tailored resume disagrees with the job's
    own match score about whether the candidate has the skill."""
    profile = _profile(skills=(_skill("Basic SQL"), _skill("Figma (basic)")))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="Must know SQL and Figma.", job_requirements=None,
    )
    assert "Basic SQL" in result.relevant_skills
    assert "Figma (basic)" in result.relevant_skills
    assert "SQL" in result.ats_keywords
    assert not any("SQL" in note for note in result.notes)
    assert not any("Figma" in note for note in result.notes)


def test_experience_ranked_by_relevance_to_job_text():
    relevant = _experience("Data Analyst", "Acme", highlights=("Built SQL dashboards",))
    irrelevant = _experience("Barista", "Cafe", highlights=("Made coffee",))
    profile = _profile(experience=(irrelevant, relevant))
    result = tailor_resume_for_job(
        profile, None, job_title="Data Analyst", job_company="Acme",
        job_description="Looking for SQL dashboard experience.", job_requirements=None,
    )
    assert result.emphasized_experience[0] is relevant


def test_projects_filtered_to_ones_relevant_to_job_text():
    relevant = _project("SQL Reporting", highlights=("Built a SQL reporting dashboard",))
    irrelevant = _project("Personal Blog", highlights=("Wrote posts",))
    profile = _profile(projects=(relevant, irrelevant))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="You will own a SQL reporting dashboard for the team.",
        job_requirements=None,
    )
    assert relevant in result.relevant_projects
    assert irrelevant not in result.relevant_projects


def test_empty_profile_never_crashes():
    profile = _profile()
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="Some description.", job_requirements=None,
    )
    assert result.professional_summary
    assert result.relevant_skills == ()


class _TruthfulLLM(LLMProvider):
    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        draft = schema(summary="A candidate with hands-on experience in SQL.")
        meta = LLMCallMetadata(
            provider="fake", model="fake-model", prompt_version=prompt_version,
            input_tokens=1, output_tokens=1, latency_ms=1.0,
        )
        return draft, meta


class _FabricatingLLM(LLMProvider):
    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        draft = schema(summary="Previously grew revenue by 200 percent at Morgan Stanley.")
        meta = LLMCallMetadata(
            provider="fake", model="fake-model", prompt_version=prompt_version,
            input_tokens=1, output_tokens=1, latency_ms=1.0,
        )
        return draft, meta


class _UnavailableLLM(LLMProvider):
    def complete_json(self, **kwargs):
        raise LLMUnavailableError("no credentials configured: api_key=sk-liveSECRET1234567890")


class _InvalidOutputLLM(LLMProvider):
    def complete_json(self, **kwargs):
        raise LLMOutputValidationError("malformed tool call")


def test_llm_truthful_summary_used():
    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", job_requirements=None, llm=_TruthfulLLM(),
    )
    assert result.generated_by == "llm"
    assert "SQL" in result.professional_summary


def test_llm_fabricated_summary_falls_back_to_deterministic():
    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", job_requirements=None, llm=_FabricatingLLM(),
    )
    assert result.generated_by == "deterministic"
    assert "Morgan Stanley" not in result.professional_summary
    assert any("unverifiable" in note.lower() for note in result.notes)


def test_llm_unavailable_falls_back_to_deterministic_without_leaking_secret():
    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", job_requirements=None, llm=_UnavailableLLM(),
    )
    assert result.generated_by == "deterministic"
    assert not any("sk-liveSECRET1234567890" in note for note in result.notes)


def test_llm_invalid_output_falls_back_to_deterministic():
    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", job_requirements=None, llm=_InvalidOutputLLM(),
    )
    assert result.generated_by == "deterministic"


def test_job_description_never_leaks_into_known_facts_for_validation():
    """Regression test: `validate_generated_answer`'s known-facts blob must be
    built from the CANDIDATE's profile only. If job-posting text were ever
    passed in as the 'resume_text' argument, a fabricated claim that merely
    echoes wording from the job posting (not from the candidate's actual
    background) would incorrectly pass validation."""

    class _EchoJobPostingLLM(LLMProvider):
        def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
            draft = schema(summary="I previously delivered a 200 percent lift at Zylodyne Corp.")
            meta = LLMCallMetadata(
                provider="fake", model="fake-model", prompt_version=prompt_version,
                input_tokens=1, output_tokens=1, latency_ms=1.0,
            )
            return draft, meta

    profile = _profile(skills=(_skill("SQL"),))
    result = tailor_resume_for_job(
        profile, None, job_title="Analyst", job_company="Acme",
        job_description="Zylodyne Corp is looking for someone to drive a 200 percent lift.",
        job_requirements=None, llm=_EchoJobPostingLLM(),
    )
    assert result.generated_by == "deterministic"
    assert "Zylodyne" not in result.professional_summary

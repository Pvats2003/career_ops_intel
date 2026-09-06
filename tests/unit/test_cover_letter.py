"""Cover letter generation (job_agent.applications.cover_letter) — Career
OS Phase 9 section 12."""

from __future__ import annotations

from job_agent.applications.cover_letter import generate_cover_letter
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
from job_agent.llm.errors import LLMOutputValidationError, LLMUnavailableError
from job_agent.llm.provider import LLMCallMetadata, LLMProvider


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
    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Business Analyst", job_company="Acme",
        job_description="Looking for someone with SQL.",
    )
    assert letter.generated_by == "deterministic"
    assert "Business Analyst" in letter.body
    assert "Acme" in letter.body


def test_letter_is_job_specific_never_generic():
    profile = _profile(skills=(_skill("SQL"),))
    letter_a = generate_cover_letter(
        profile, job_title="Business Analyst", job_company="Acme", job_description=None,
    )
    letter_b = generate_cover_letter(
        profile, job_title="Product Manager", job_company="Globex", job_description=None,
    )
    assert letter_a.body != letter_b.body
    assert "Product Manager" not in letter_a.body
    assert "Business Analyst" not in letter_b.body


def test_never_fabricates_skills_beyond_profile():
    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme",
        job_description="Looking for Python and Tableau experience.",
    )
    assert "Python" not in letter.body
    assert "Tableau" not in letter.body


def test_empty_profile_never_crashes():
    profile = _profile()
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme", job_description="Some description.",
    )
    assert letter.body
    assert "Analyst" in letter.body
    assert "Acme" in letter.body


class _TruthfulLLM(LLMProvider):
    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        draft = schema(body="I have hands-on experience with SQL that fits this role well.")
        meta = LLMCallMetadata(
            provider="fake", model="fake-model", prompt_version=prompt_version,
            input_tokens=1, output_tokens=1, latency_ms=1.0,
        )
        return draft, meta


class _FabricatingLLM(LLMProvider):
    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        draft = schema(body="I previously grew revenue by 200 percent at Morgan Stanley.")
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


def test_llm_truthful_letter_used():
    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", llm=_TruthfulLLM(),
    )
    assert letter.generated_by == "llm"
    assert "SQL" in letter.body


def test_llm_fabricated_letter_falls_back_to_deterministic():
    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", llm=_FabricatingLLM(),
    )
    assert letter.generated_by == "deterministic"
    assert "Morgan Stanley" not in letter.body
    assert any("unverifiable" in note.lower() for note in letter.notes)


def test_llm_unavailable_falls_back_without_leaking_secret():
    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", llm=_UnavailableLLM(),
    )
    assert letter.generated_by == "deterministic"
    assert not any("sk-liveSECRET1234567890" in note for note in letter.notes)


def test_llm_invalid_output_falls_back_to_deterministic():
    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme",
        job_description="SQL required.", llm=_InvalidOutputLLM(),
    )
    assert letter.generated_by == "deterministic"


def test_job_description_never_leaks_into_known_facts_for_validation():
    class _EchoJobPostingLLM(LLMProvider):
        def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
            draft = schema(body="I previously delivered a 200 percent lift at Zylodyne Corp.")
            meta = LLMCallMetadata(
                provider="fake", model="fake-model", prompt_version=prompt_version,
                input_tokens=1, output_tokens=1, latency_ms=1.0,
            )
            return draft, meta

    profile = _profile(skills=(_skill("SQL"),))
    letter = generate_cover_letter(
        profile, job_title="Analyst", job_company="Acme",
        job_description="Zylodyne Corp is looking for someone to drive a 200 percent lift.",
        llm=_EchoJobPostingLLM(),
    )
    assert letter.generated_by == "deterministic"
    assert "Zylodyne" not in letter.body

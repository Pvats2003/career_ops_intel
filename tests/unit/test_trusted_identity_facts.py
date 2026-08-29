"""Phase 6D — trusted candidate identity/contact fact resolution in
`answer_engine.generate_answer()`.

Every test here uses an entirely SYNTHETIC `CandidateProfile` constructed
directly in Python (never `candidate/profile.md`, never the `real_profile`
fixture) — no real personal information appears anywhere in this file, per
this checkpoint's explicit instruction. Values like "Test Candidate" and
"test@example.invalid" are obvious synthetic placeholders, never real data.

No network call, no browser, no LLM call for the five identity/contact
question labels this checkpoint maps — proven directly via a spy
`LLMProvider` that records whether it was ever invoked.
"""

from __future__ import annotations

from job_agent.applications.answer_bank import AnswerBankEntry
from job_agent.applications.answer_engine import generate_answer
from job_agent.applications.schema import ApplicationQuestion, QuestionCategory
from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.llm.errors import LLMUnavailableError
from job_agent.llm.provider import LLMProvider

SYNTHETIC_FULL_NAME = "Test Candidate"
SYNTHETIC_EMAIL = "test@example.invalid"
SYNTHETIC_PHONE = "+10000000000"
SYNTHETIC_LOCATION = "Test City"
SYNTHETIC_LINKEDIN = "https://linkedin.example/test-candidate"


class _SpyLLMProvider(LLMProvider):
    """Never makes a real call; records whether it was ever asked to."""

    def __init__(self) -> None:
        self.call_count = 0

    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        self.call_count += 1
        raise LLMUnavailableError("spy provider — never actually configured")


def _fact(value: str, *, verified: bool = True, confidence: float = 1.0) -> Fact[str]:
    return Fact[str](
        value=value, source="test_synthetic_profile", confidence=confidence, verified=verified
    )


def _synthetic_profile(
    *,
    identity_name: Fact[str] | None = None,
    identity_current_location: Fact[str] | None = None,
    contact_email: Fact[str] | None = None,
    contact_phone: Fact[str] | None = None,
    contact_linkedin: Fact[str] | None = None,
) -> CandidateProfile:
    """A minimal, fully-synthetic, otherwise-empty CandidateProfile — every
    identity/contact fact defaults to a verified synthetic value but can be
    overridden per test to exercise unverified/unknown/missing cases."""
    unknown_pref = Fact.unknown(source="test_synthetic_profile")
    return CandidateProfile(
        identity_name=identity_name or _fact(SYNTHETIC_FULL_NAME),
        identity_current_location=identity_current_location or _fact(SYNTHETIC_LOCATION),
        contact_email=contact_email or _fact(SYNTHETIC_EMAIL),
        contact_phone=contact_phone or _fact(SYNTHETIC_PHONE),
        contact_linkedin=contact_linkedin or _fact(SYNTHETIC_LINKEDIN),
        target_roles=TargetRoles(),
        work_preferences=WorkPreferences(
            remote=unknown_pref, willing_to_relocate=unknown_pref, notice_period=unknown_pref
        ),
        location_preferences=LocationPreferences(
            current_location=identity_current_location or _fact(SYNTHETIC_LOCATION),
            open_to_countries=unknown_pref,
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown_pref, minimum_annual=unknown_pref,
            target_annual=unknown_pref, negotiable=unknown_pref,
        ),
        visa_information=VisaInformation(
            nationality=unknown_pref, requires_sponsorship_us=unknown_pref,
            requires_sponsorship_uk=unknown_pref, requires_sponsorship_eu=unknown_pref,
            requires_sponsorship_other=unknown_pref,
        ),
    )


def _question(
    text: str, category: QuestionCategory = QuestionCategory.CUSTOM
) -> ApplicationQuestion:
    return ApplicationQuestion(text=text, category=category, required=True)


def _generate(text: str, profile: CandidateProfile, llm: LLMProvider | None = None):
    return generate_answer(_question(text), profile, "", [], llm or _SpyLLMProvider())


# ==========================================================================
# A-E: each verified fact resolves deterministically
# ==========================================================================
def test_full_name_resolves_deterministically():
    profile = _synthetic_profile()
    answer = _generate("Full name", profile)
    assert answer.answer == SYNTHETIC_FULL_NAME
    assert answer.requires_human is False


def test_email_resolves_deterministically():
    profile = _synthetic_profile()
    answer = _generate("Email", profile)
    assert answer.answer == SYNTHETIC_EMAIL
    assert answer.requires_human is False


def test_phone_resolves_deterministically():
    profile = _synthetic_profile()
    answer = _generate("Phone", profile)
    assert answer.answer == SYNTHETIC_PHONE
    assert answer.requires_human is False


def test_current_location_resolves_deterministically():
    profile = _synthetic_profile()
    answer = _generate("Current location", profile)
    assert answer.answer == SYNTHETIC_LOCATION
    assert answer.requires_human is False


def test_linkedin_url_resolves_deterministically():
    profile = _synthetic_profile()
    answer = _generate("LinkedIn URL", profile)
    assert answer.answer == SYNTHETIC_LINKEDIN
    assert answer.requires_human is False


# ==========================================================================
# F-G: source is the trusted fact, never the LLM; LLM never invoked
# ==========================================================================
def test_source_identifies_trusted_candidate_fact_not_llm():
    profile = _synthetic_profile()
    mapping = {
        "Full name": "identity_name",
        "Email": "contact_email",
        "Phone": "contact_phone",
        "Current location": "identity_current_location",
        "LinkedIn URL": "contact_linkedin",
    }
    for label, attr in mapping.items():
        answer = _generate(label, profile)
        assert answer.source == f"candidate_fact:{attr}", label
        assert not answer.source.startswith("llm"), label
        assert not answer.source.startswith("answer_bank"), label


def test_llm_is_never_invoked_for_the_five_trusted_fields():
    profile = _synthetic_profile()
    spy = _SpyLLMProvider()
    for label in ("Full name", "Email", "Phone", "Current location", "LinkedIn URL"):
        _generate(label, profile, llm=spy)
    assert spy.call_count == 0


# ==========================================================================
# H-I: unverified/unknown/missing facts remain HUMAN_REQUIRED, never guessed
# ==========================================================================
def test_unverified_fact_remains_human_required():
    profile = _synthetic_profile(identity_name=_fact(SYNTHETIC_FULL_NAME, verified=False))
    answer = _generate("Full name", profile)
    assert answer.answer is None
    assert answer.requires_human is True
    assert answer.source == "candidate_fact_unverified:identity_name"


def test_unknown_fact_remains_human_required():
    unknown = Fact.unknown(source="test_synthetic_profile")
    profile = _synthetic_profile(contact_email=unknown)
    answer = _generate("Email", profile)
    assert answer.answer is None
    assert answer.requires_human is True
    assert answer.source == "candidate_fact_unverified:contact_email"


def test_missing_value_is_never_fabricated_llm_still_not_invoked():
    """An unverified/unknown trusted fact still short-circuits before the
    LLM tier -- it fails closed on its own, it never falls through to a
    model-generated guess."""
    spy = _SpyLLMProvider()
    profile = _synthetic_profile(contact_phone=Fact.unknown(source="test_synthetic_profile"))
    answer = _generate("Phone", profile, llm=spy)
    assert answer.answer is None
    assert answer.requires_human is True
    assert spy.call_count == 0


# ==========================================================================
# J-K: current_company has no mapping, is never inferred from experience
# ==========================================================================
def test_current_company_remains_human_required():
    profile = _synthetic_profile()
    answer = _generate("Current company", profile)
    assert answer.answer is None
    assert answer.requires_human is True
    assert not answer.source.startswith("candidate_fact")


def test_current_company_not_inferred_even_with_experience_present():
    """Confirms the mapping is truly absent, not merely untested: even a
    profile with concrete `experience` entries never has "Current company"
    resolved from them."""
    from job_agent.candidate.schema import ExperienceEntry

    profile = _synthetic_profile().model_copy(
        update={
            "experience": (
                ExperienceEntry(
                    title="Test Title", company="Test Company Inc.",
                    start_date="2020-01", end_date="present",
                    source="test_synthetic_profile",
                ),
            )
        }
    )
    answer = _generate("Current company", profile)
    assert answer.answer is None
    assert answer.requires_human is True


# ==========================================================================
# L-M: neither the answer bank nor the LLM can override a verified fact
# ==========================================================================
def test_answer_bank_resolution_is_never_reached_for_a_verified_identity_fact(monkeypatch):
    """`match_slug()`'s fixed keyword table (candidate/answers/*.md's
    narrative slugs) has no entry that matches "Full name"/"Email"/etc.
    today, so there's no way to construct a real AnswerBankEntry that
    would even be offered a chance to override one of these five labels
    through the normal pipeline. The real guarantee this proves is
    structural: `generate_answer()` returns from the trusted-fact tier
    BEFORE `match_slug()` is ever called at all -- proven here by making
    match_slug() explode if reached."""
    import job_agent.applications.answer_engine as answer_engine_module

    def _must_not_be_called(question_text: str) -> str | None:
        raise AssertionError("match_slug() must never be reached for a verified trusted fact")

    monkeypatch.setattr(answer_engine_module, "match_slug", _must_not_be_called)

    profile = _synthetic_profile()
    answer = _generate("Full name", profile)
    assert answer.answer == SYNTHETIC_FULL_NAME
    assert answer.source == "candidate_fact:identity_name"


def test_llm_cannot_override_a_verified_identity_fact():
    profile = _synthetic_profile()

    class _WouldFabricateLLM(LLMProvider):
        def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
            raise AssertionError("the LLM must never be reached for a verified trusted fact")

    answer = _generate("Email", profile, llm=_WouldFabricateLLM())
    assert answer.answer == SYNTHETIC_EMAIL
    assert answer.source == "candidate_fact:contact_email"


# ==========================================================================
# Deliberate exclusions: bare "name"/"location" are too ambiguous to map
# ==========================================================================
def test_bare_company_name_label_does_not_resolve_to_candidate_identity():
    profile = _synthetic_profile()
    answer = _generate("Company name", profile, llm=_SpyLLMProvider())
    assert answer.answer != SYNTHETIC_FULL_NAME
    assert not answer.source.startswith("candidate_fact")


def test_reference_name_label_does_not_resolve_to_candidate_identity():
    profile = _synthetic_profile()
    answer = _generate("Reference name", profile, llm=_SpyLLMProvider())
    assert answer.answer != SYNTHETIC_FULL_NAME
    assert not answer.source.startswith("candidate_fact")


def test_job_location_label_does_not_resolve_to_candidate_location():
    profile = _synthetic_profile()
    answer = _generate("Job location", profile, llm=_SpyLLMProvider())
    assert answer.answer != SYNTHETIC_LOCATION
    assert not answer.source.startswith("candidate_fact")


def test_relocation_question_does_not_resolve_to_candidate_location():
    profile = _synthetic_profile()
    answer = _generate("Are you willing to relocate?", profile, llm=_SpyLLMProvider())
    assert answer.answer != SYNTHETIC_LOCATION
    assert not answer.source.startswith("candidate_fact")


# ==========================================================================
# N-O: existing narrative/hard-block behavior is completely unchanged
# ==========================================================================
def test_narrative_question_still_uses_answer_bank_resolution():
    profile = _synthetic_profile()
    bank_entry = AnswerBankEntry(
        slug="strengths", category=QuestionCategory.MOTIVATION, requires_human=False,
        body="A human-authored narrative answer.", source="test_synthetic_bank",
    )
    answer = generate_answer(
        _question("What is your greatest strength?", QuestionCategory.MOTIVATION),
        profile, "", [bank_entry], _SpyLLMProvider(),
    )
    assert answer.answer == "A human-authored narrative answer."
    assert answer.source == "answer_bank:strengths"


def test_hard_block_category_still_short_circuits_before_trusted_facts():
    profile = _synthetic_profile()
    answer = _generate("What is your expected salary?", profile, llm=_SpyLLMProvider())
    assert answer.answer is None
    assert answer.requires_human is True
    assert answer.source.startswith("hard_block:")

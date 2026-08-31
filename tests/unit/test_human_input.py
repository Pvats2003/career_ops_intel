"""Real-target-readiness checkpoint: `apply_human_input_overrides` —
letting a human supply a value for a question the answer engine already
correctly left unresolved (e.g. "Current company"), without touching
CandidateProfile, without a second LLM call, and always distinguishable
from a trusted fact via its `source` string.

Pure, offline unit tests — no browser, no network, no database. Uses
only fabricated `GeneratedAnswer`/`ApplicationQuestion` objects and a
fully synthetic `CandidateProfile`, never real candidate data.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from job_agent.applications.answer_engine import generate_answer
from job_agent.applications.human_input import (
    HUMAN_INPUT_SOURCE_PREFIX,
    apply_human_input_overrides,
)
from job_agent.applications.schema import ApplicationQuestion, GeneratedAnswer, QuestionCategory
from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.llm.provider import LLMCallMetadata, LLMProvider, NullLLMProvider


def _synthetic_profile() -> CandidateProfile:
    unknown = Fact.unknown(source="test_synthetic_profile")
    return CandidateProfile(
        identity_name=Fact[str](
            value="Test Candidate", source="test_synthetic_profile",
            confidence=1.0, verified=True,
        ),
        identity_current_location=unknown,
        contact_email=unknown,
        contact_phone=unknown,
        contact_linkedin=unknown,
        target_roles=TargetRoles(),
        work_preferences=WorkPreferences(
            remote=unknown, willing_to_relocate=unknown, notice_period=unknown,
        ),
        location_preferences=LocationPreferences(
            current_location=unknown, open_to_countries=unknown,
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown, minimum_annual=unknown,
            target_annual=unknown, negotiable=unknown,
        ),
        visa_information=VisaInformation(
            nationality=unknown, requires_sponsorship_us=unknown,
            requires_sponsorship_uk=unknown, requires_sponsorship_eu=unknown,
            requires_sponsorship_other=unknown,
        ),
    )


def _unresolved_answer(question: str) -> GeneratedAnswer:
    return GeneratedAnswer(
        question=question, category=QuestionCategory.CUSTOM, answer=None,
        confidence=0.0, source="no_trusted_fact:current_company",
        requires_human=True, validated=True, validation_notes=("test",),
    )


def _resolved_answer(question: str) -> GeneratedAnswer:
    return GeneratedAnswer(
        question=question, category=QuestionCategory.CONTACT, answer="trusted-value",
        confidence=1.0, source="candidate_fact:contact_email",
        requires_human=False, validated=True, validation_notes=(),
    )


def test_override_resolves_a_currently_unresolved_question():
    answers = [_unresolved_answer("Current company")]
    updated = apply_human_input_overrides(answers, {"Current company": "Instawork"})
    assert len(updated) == 1
    result = updated[0]
    assert result.answer == "Instawork"
    assert result.requires_human is False
    assert result.source == f"{HUMAN_INPUT_SOURCE_PREFIX}Current company"


def test_override_never_replaces_an_already_resolved_answer():
    """A trusted fact, an answer-bank hit, or a validated LLM draft is
    never silently overridden -- only requires_human=True answers are
    eligible."""
    answers = [_resolved_answer("Email")]
    updated = apply_human_input_overrides(answers, {"Email": "attacker@example.test"})
    assert updated[0].answer == "trusted-value"
    assert updated[0].source == "candidate_fact:contact_email"
    assert updated[0].requires_human is False


def test_override_with_no_matching_question_is_a_no_op():
    answers = [_unresolved_answer("Current company")]
    updated = apply_human_input_overrides(answers, {"Typo'd Question": "value"})
    assert updated == answers


def test_empty_overrides_returns_the_same_list_object():
    answers = [_unresolved_answer("Current company")]
    assert apply_human_input_overrides(answers, {}) is answers


def test_override_source_always_carries_the_human_input_prefix():
    answers = [_unresolved_answer("Current company")]
    updated = apply_human_input_overrides(answers, {"Current company": "Instawork"})
    assert updated[0].source.startswith(HUMAN_INPUT_SOURCE_PREFIX)
    assert not updated[0].source.startswith("candidate_fact:")


def test_current_company_still_never_reaches_the_llm_even_with_an_override_pending():
    """The deterministic current-company guard in answer_engine.py runs
    BEFORE any override is ever applied -- an --answer override changes
    nothing about how generate_answer() itself resolves the question."""

    class _ExplodingLLM(LLMProvider):
        def complete_json(self, **kwargs):
            raise AssertionError("must never call the LLM for current company")

    profile = _synthetic_profile()
    question = ApplicationQuestion(text="Current company", category=QuestionCategory.CUSTOM)
    answer = generate_answer(question, profile, "", [], _ExplodingLLM())
    assert answer.requires_human is True

    updated = apply_human_input_overrides([answer], {"Current company": "Instawork"})
    assert updated[0].answer == "Instawork"
    assert updated[0].source == f"{HUMAN_INPUT_SOURCE_PREFIX}Current company"


def test_apply_human_input_overrides_has_no_llm_parameter():
    """Structural guarantee, not just a behavioral one: this function
    cannot call an LLM even by accident in some future edit, because it
    is never given one to call."""
    params = inspect.signature(apply_human_input_overrides).parameters
    assert "llm" not in params
    assert "profile" not in params
    assert "candidate" not in params


def test_human_input_override_never_triggers_a_second_llm_call():
    """The override is applied strictly AFTER the full answers list
    already exists -- proves no additional LLM call happens as a result
    of applying an override, using a real (non-hard-blocked, non-
    current-company) custom question that DOES legitimately reach the
    LLM tier once."""

    class _CountingLLM(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
            self.calls += 1
            draft = schema(answer="I enjoy chess.", confidence=80)
            meta = LLMCallMetadata(
                provider="fake", model="fake-model", prompt_version=prompt_version,
                input_tokens=1, output_tokens=1, latency_ms=1.0,
            )
            return draft, meta

    llm = _CountingLLM()
    profile = _synthetic_profile()
    question = ApplicationQuestion(
        text="What is your favorite hobby?", category=QuestionCategory.CUSTOM,
    )
    answer = generate_answer(question, profile, "", [], llm)
    assert llm.calls == 1

    # Even though this question already resolved (requires_human=False),
    # attempt an override anyway -- must be ignored, and must not trigger
    # any further LLM activity.
    updated = apply_human_input_overrides(
        [answer], {"What is your favorite hobby?": "Something else entirely"}
    )
    assert llm.calls == 1
    assert updated[0].answer == answer.answer


def test_null_llm_then_human_override_never_calls_a_real_llm():
    """Mirrors the real CLI ordering: generate_answer() first (with
    whatever LLM is configured), THEN apply_human_input_overrides() --
    never the other order, and never re-entering generate_answer()."""
    profile = _synthetic_profile()
    question = ApplicationQuestion(
        text="What is your favorite programming paradigm?", category=QuestionCategory.CUSTOM,
    )
    answer = generate_answer(question, profile, "", [], NullLLMProvider())
    assert answer.requires_human is True
    assert answer.source == "llm_unavailable"

    updated = apply_human_input_overrides(
        [answer], {"What is your favorite programming paradigm?": "Functional programming"}
    )
    assert updated[0].requires_human is False
    assert updated[0].answer == "Functional programming"
    assert updated[0].source.startswith(HUMAN_INPUT_SOURCE_PREFIX)


# Actual call/reference sites, not English prose -- a docstring
# explaining "BrowserApplicationProvider.submit() remains structurally
# incapable of that" is EXPECTED and must not fail this check; an actual
# call to one of these would be a real safety-boundary violation.
_FORBIDDEN_CALL_PATTERNS = (
    "create_allowlist_entry(",
    "revoke_allowlist_entry(",
    "create_approval(",
    "compute_answer_fingerprint(",
    "submit_application(",
    "verify_application(",
    "provider.submit(",
    "provider.verify(",
    "EnvCredentialStore",
    "SubmissionHttpClient",
)


def test_human_input_module_never_calls_allowlist_approval_submit_or_credential_code():
    source = Path("src/job_agent/applications/human_input.py").read_text()
    for term in _FORBIDDEN_CALL_PATTERNS:
        assert term not in source


def test_browser_preview_command_never_calls_allowlist_approval_submit_or_credential_code():
    """The --answer/human-input wiring added to `applications
    browser-preview` in this checkpoint sits inside a command that has
    never called into allowlist/approval/submit()/verify()/credential
    code at all -- checked over the WHOLE function body (old code and
    new), since a human-input override could only ever reach one of
    those by this command starting to call it somewhere."""
    source = Path("src/job_agent/cli/main.py").read_text()
    start = source.index('@applications_app.command("browser-preview")')
    end = source.index('@applications_app.command("run")')
    body = source[start:end]
    for term in _FORBIDDEN_CALL_PATTERNS:
        assert term not in body


def test_target_add_command_never_calls_allowlist_approval_submit_or_credential_code():
    source = Path("src/job_agent/cli/main.py").read_text()
    start = source.index('@applications_app.command("target-add")')
    end = source.index('@applications_app.command("browser-preview")')
    body = source[start:end]
    for term in _FORBIDDEN_CALL_PATTERNS:
        assert term not in body

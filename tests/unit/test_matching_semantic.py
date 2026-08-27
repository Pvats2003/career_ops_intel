from __future__ import annotations

from job_agent.llm.errors import LLMOutputValidationError, LLMUnavailableError
from job_agent.llm.provider import LLMCallMetadata, LLMProvider
from job_agent.matching.deterministic import JobText
from job_agent.matching.semantic import SemanticMatchResult, run_semantic_match

JOB = JobText(title="Associate Product Manager", company="Acme", description="Own the roadmap.")


class _AlwaysUnavailable(LLMProvider):
    def complete_json(self, **kwargs):
        raise LLMUnavailableError("no key configured")


class _AlwaysInvalid(LLMProvider):
    def __init__(self):
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        raise LLMOutputValidationError("bad json")


class _FailsOnceThenSucceeds(LLMProvider):
    def __init__(self):
        self.calls = 0

    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        self.calls += 1
        if self.calls == 1:
            raise LLMOutputValidationError("transient bad output")
        result = schema(
            role_alignment_score=80,
            experience_similarity_score=60,
            project_relevance_score=50,
            transferable_skills=(),
            additional_concerns=(),
            additional_missing_requirements=(),
            reasoning="ok",
        )
        meta = LLMCallMetadata(
            provider="fake", model="fake-model", prompt_version=prompt_version,
            input_tokens=1, output_tokens=1, latency_ms=1.0,
        )
        return result, meta


class _Succeeds(LLMProvider):
    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        assert "<job_posting>" in user_prompt
        assert JOB.title in user_prompt
        result = schema(
            role_alignment_score=90,
            experience_similarity_score=70,
            project_relevance_score=65,
            transferable_skills=("scoping",),
            additional_concerns=("note",),
            additional_missing_requirements=("MBA",),
            reasoning="good fit",
        )
        meta = LLMCallMetadata(
            provider="fake", model="fake-model", prompt_version=prompt_version,
            input_tokens=1, output_tokens=1, latency_ms=1.0,
        )
        return result, meta


def test_run_semantic_match_success(real_profile):
    outcome = run_semantic_match(_Succeeds(), real_profile, JOB)
    assert outcome.available is True
    assert isinstance(outcome.result, SemanticMatchResult)
    assert outcome.result.role_alignment_score == 90
    assert outcome.metadata is not None


def test_run_semantic_match_unavailable(real_profile):
    outcome = run_semantic_match(_AlwaysUnavailable(), real_profile, JOB)
    assert outcome.available is False
    assert "no key configured" in outcome.unavailable_reason


def test_run_semantic_match_retries_once_then_fails(real_profile):
    provider = _AlwaysInvalid()
    outcome = run_semantic_match(provider, real_profile, JOB)
    assert outcome.available is False
    assert provider.calls == 2
    assert "retry" in outcome.unavailable_reason


def test_run_semantic_match_succeeds_on_retry(real_profile):
    provider = _FailsOnceThenSucceeds()
    outcome = run_semantic_match(provider, real_profile, JOB)
    assert outcome.available is True
    assert provider.calls == 2


def test_candidate_facts_exclude_pii(real_profile):
    """Data-minimization: name/email/phone must never reach the prompt."""
    from job_agent.matching.semantic import _build_candidate_facts

    facts = _build_candidate_facts(real_profile)
    facts_str = str(facts)
    assert real_profile.contact_email.value not in facts_str
    assert real_profile.contact_phone.value not in facts_str
    assert real_profile.identity_name.value not in facts_str

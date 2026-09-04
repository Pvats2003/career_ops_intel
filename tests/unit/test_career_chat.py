"""Career Chat — Career OS FINAL GOD MODE Part 7.20. Every answer must be
grounded in the CAREER_OS_DATA context passed in, never generic
knowledge — and with no LLM configured, the real data is returned
directly rather than a fabricated "AI" answer."""

from __future__ import annotations

from job_agent.candidate.career_chat import answer_career_question
from job_agent.llm.errors import LLMOutputValidationError, LLMUnavailableError
from job_agent.llm.provider import LLMCallMetadata, LLMProvider

_CONTEXT = {
    "top_jobs": [
        {
            "title": "Business Analyst",
            "company": "Acme",
            "score": 91,
            "why": "Strong overlap with your SQL and stakeholder management background.",
        },
        {
            "title": "Data Analyst",
            "company": "Globex",
            "score": 78,
            "why": "Good fit but missing Tableau.",
        },
    ],
    "career_profile": {"primary_direction": "Business Analysis"},
    "follow_ups": [],
}


class _EchoLLM(LLMProvider):
    def complete_json(self, *, system, user_prompt, schema, tool_name, prompt_version):
        draft = schema(answer="Apply to Business Analyst at Acme — it's your top match at 91%.")
        meta = LLMCallMetadata(
            provider="fake",
            model="fake-model",
            prompt_version=prompt_version,
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
        )
        return draft, meta


class _UnavailableLLM(LLMProvider):
    def complete_json(self, **kwargs):
        raise LLMUnavailableError("no credentials configured")


class _InvalidOutputLLM(LLMProvider):
    def complete_json(self, **kwargs):
        raise LLMOutputValidationError("malformed tool call")


def test_no_llm_returns_real_data_directly():
    response = answer_career_question("What are the best jobs for me?", _CONTEXT, llm=None)
    assert response.generated_by == "deterministic"
    assert "Business Analyst" in response.answer
    assert "Acme" in response.answer
    assert "91" in response.answer


def test_no_llm_and_no_jobs_says_so_honestly():
    response = answer_career_question("What are the best jobs?", {"top_jobs": []}, llm=None)
    assert response.generated_by == "deterministic"
    assert "no ai assistant" in response.answer.lower()
    assert "run a search" in response.answer.lower()


def test_llm_answer_used_when_available():
    response = answer_career_question("What are the best jobs for me?", _CONTEXT, llm=_EchoLLM())
    assert response.generated_by == "llm"
    assert "Business Analyst" in response.answer


def test_llm_unavailable_falls_back_to_real_data():
    response = answer_career_question("What are the best jobs?", _CONTEXT, llm=_UnavailableLLM())
    assert response.generated_by == "deterministic"
    assert "Business Analyst" in response.answer


def test_llm_invalid_output_falls_back_to_real_data():
    response = answer_career_question("What are the best jobs?", _CONTEXT, llm=_InvalidOutputLLM())
    assert response.generated_by == "deterministic"
    assert "Acme" in response.answer


def test_llm_unavailable_error_message_is_redacted_in_fallback_note():
    class _LeakyLLM(LLMProvider):
        def complete_json(self, **kwargs):
            raise LLMUnavailableError("failed: api_key=sk-liveSECRET1234567890")

    response = answer_career_question("best jobs?", _CONTEXT, llm=_LeakyLLM())
    assert "sk-liveSECRET1234567890" not in response.answer

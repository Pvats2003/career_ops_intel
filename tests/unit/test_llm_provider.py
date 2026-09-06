from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from job_agent.config.loader import load_config
from job_agent.llm.errors import LLMOutputValidationError, LLMUnavailableError
from job_agent.llm.provider import AnthropicLLMProvider, NullLLMProvider, build_llm_provider


class DummySchema(BaseModel):
    x: int


def test_null_provider_raises_unavailable():
    provider = NullLLMProvider()
    with pytest.raises(LLMUnavailableError):
        provider.complete_json(
            system="s", user_prompt="u", schema=DummySchema, tool_name="t", prompt_version="v1"
        )


def test_build_llm_provider_falls_back_to_null_without_api_key(real_config):
    provider = build_llm_provider(real_config)
    assert isinstance(provider, NullLLMProvider)


def test_build_llm_provider_uses_anthropic_when_key_present(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
    cfg = load_config()
    provider = build_llm_provider(cfg)
    assert isinstance(provider, AnthropicLLMProvider)


# --- AnthropicLLMProvider, fully mocked (no real network call) -------------


@dataclass
class _FakeToolUseBlock:
    type: str
    input: dict


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResponse:
    content: list
    usage: _FakeUsage


class _FakeMessages:
    def __init__(self, response):
        self._response = response

    def create(self, **kwargs):
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _make_provider(monkeypatch, response) -> AnthropicLLMProvider:
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: _FakeAnthropicClient(response))
    return AnthropicLLMProvider(api_key="sk-fake", model="fake-model")


def test_anthropic_provider_parses_valid_tool_use(monkeypatch):
    response = _FakeResponse(
        content=[_FakeToolUseBlock(type="tool_use", input={"x": 42})],
        usage=_FakeUsage(input_tokens=5, output_tokens=5),
    )
    provider = _make_provider(monkeypatch, response)
    result, meta = provider.complete_json(
        system="s", user_prompt="u", schema=DummySchema, tool_name="t", prompt_version="v1"
    )
    assert result.x == 42
    assert meta.model == "fake-model"
    assert meta.prompt_version == "v1"


def test_anthropic_provider_raises_on_missing_tool_use_block(monkeypatch):
    response = _FakeResponse(content=[], usage=_FakeUsage(input_tokens=1, output_tokens=1))
    provider = _make_provider(monkeypatch, response)
    with pytest.raises(LLMOutputValidationError):
        provider.complete_json(
            system="s", user_prompt="u", schema=DummySchema, tool_name="t", prompt_version="v1"
        )


def test_anthropic_provider_raises_on_schema_mismatch(monkeypatch):
    response = _FakeResponse(
        content=[_FakeToolUseBlock(type="tool_use", input={"x": "not-an-int"})],
        usage=_FakeUsage(input_tokens=1, output_tokens=1),
    )
    provider = _make_provider(monkeypatch, response)
    with pytest.raises(LLMOutputValidationError):
        provider.complete_json(
            system="s", user_prompt="u", schema=DummySchema, tool_name="t", prompt_version="v1"
        )


# --- Part 17 cost audit: every real Anthropic call logs its real usage -----


def test_anthropic_provider_logs_real_token_usage(monkeypatch, caplog):
    """Every real API call must log real usage from the API's own response
    (never an estimate), so per-feature LLM cost is actually observable
    instead of being computed and silently discarded (the exact gap this
    test guards against regressing)."""
    import logging

    response = _FakeResponse(
        content=[_FakeToolUseBlock(type="tool_use", input={"x": 42})],
        usage=_FakeUsage(input_tokens=123, output_tokens=45),
    )
    provider = _make_provider(monkeypatch, response)
    with caplog.at_level(logging.INFO, logger="job_agent.llm.cost"):
        provider.complete_json(
            system="s", user_prompt="u", schema=DummySchema, tool_name="t", prompt_version="v1"
        )

    records = [r for r in caplog.records if r.name == "job_agent.llm.cost"]
    assert len(records) == 1
    data = records[0].event_data
    assert data["input_tokens"] == 123
    assert data["output_tokens"] == 45
    assert data["model"] == "fake-model"
    assert data["prompt_version"] == "v1"
    assert data["result"] == "success"


def test_anthropic_provider_does_not_log_on_failure(monkeypatch, caplog):
    """A failed call never produced real usage data, so it must not log a
    (fabricated) usage line — only a genuinely completed call is logged."""
    import logging

    response = _FakeResponse(content=[], usage=_FakeUsage(input_tokens=1, output_tokens=1))
    provider = _make_provider(monkeypatch, response)
    with caplog.at_level(logging.INFO, logger="job_agent.llm.cost"):
        with pytest.raises(LLMOutputValidationError):
            provider.complete_json(
                system="s", user_prompt="u", schema=DummySchema, tool_name="t", prompt_version="v1"
            )

    assert [r for r in caplog.records if r.name == "job_agent.llm.cost"] == []

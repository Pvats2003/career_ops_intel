"""LLM provider abstraction — BUILD PROMPT section 27.

The rest of the system (the semantic matcher today; resume tailoring and
answer generation in later phases) is written against `LLMProvider.
complete_json()`, never against a specific vendor SDK, so switching models
or providers is a config change, not a code change.

`complete_json()` is the one primitive: send a system + user prompt, force
a structured JSON response via tool-use, and return it already validated
against a Pydantic schema (section 29 — no unvalidated LLM output is ever
allowed to reach calling code). Malformed output raises
`LLMOutputValidationError`; callers own the retry-once-then-fallback policy
described in section 29, since what "fallback" means differs per caller
(semantic matching falls back to deterministic-only, answer generation
would fall back to HUMAN_REQUIRED, etc).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from job_agent.config.loader import AppConfig
from job_agent.llm.errors import LLMOutputValidationError, LLMUnavailableError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class LLMCallMetadata:
    provider: str
    model: str
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(
        self,
        *,
        system: str,
        user_prompt: str,
        schema: type[SchemaT],
        tool_name: str,
        prompt_version: str,
    ) -> tuple[SchemaT, LLMCallMetadata]:
        """Return a validated `schema` instance plus call metadata.

        Raises `LLMUnavailableError` if no provider is configured/reachable,
        or `LLMOutputValidationError` if the model's response doesn't parse.
        """


class NullLLMProvider(LLMProvider):
    """Used when no LLM is configured. Never makes a network call — the
    absence of an API key is a normal, expected state (BUILD PROMPT section
    36's safe-by-default posture), not an error condition to work around."""

    def complete_json(
        self,
        *,
        system: str,
        user_prompt: str,
        schema: type[SchemaT],
        tool_name: str,
        prompt_version: str,
    ) -> tuple[SchemaT, LLMCallMetadata]:
        raise LLMUnavailableError(
            "No LLM provider configured (set ANTHROPIC_API_KEY to enable semantic matching)."
        )


class AnthropicLLMProvider(LLMProvider):
    """Real implementation against the Anthropic Messages API.

    Uses forced tool-use (`tool_choice`) so the model's response is
    constrained to the target schema's JSON shape at the API level, rather
    than hoping a free-text response parses as JSON.
    """

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        import anthropic  # imported lazily so NullLLMProvider needs no dependency

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def complete_json(
        self,
        *,
        system: str,
        user_prompt: str,
        schema: type[SchemaT],
        tool_name: str,
        prompt_version: str,
    ) -> tuple[SchemaT, LLMCallMetadata]:
        input_schema = schema.model_json_schema()
        input_schema.pop("title", None)

        start = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": f"Report the {tool_name} result as structured data.",
                        "input_schema": input_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )
        except Exception as exc:  # noqa: BLE001 — any transport/API failure
            raise LLMOutputValidationError(f"Anthropic API call failed: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            raise LLMOutputValidationError("model response did not include a tool_use block")

        try:
            parsed = schema.model_validate(tool_use_blocks[0].input)
        except ValidationError as exc:
            raise LLMOutputValidationError(
                f"tool_use input failed schema validation: {exc}"
            ) from exc

        usage = getattr(response, "usage", None)
        meta = LLMCallMetadata(
            provider="anthropic",
            model=self.model,
            prompt_version=prompt_version,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=latency_ms,
        )
        return parsed, meta


def build_llm_provider(config: AppConfig) -> LLMProvider:
    """Select a provider based on config — never crashes when unconfigured."""
    if config.env.llm_provider == "anthropic" or config.automation.llm.provider == "anthropic":
        if config.env.anthropic_api_key:
            model = config.env.llm_model or config.automation.llm.model
            return AnthropicLLMProvider(api_key=config.env.anthropic_api_key, model=model)
    return NullLLMProvider()

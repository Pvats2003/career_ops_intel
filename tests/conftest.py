from __future__ import annotations

import pytest

from job_agent.candidate.parser import parse_candidate_profile
from job_agent.config.loader import REPO_ROOT, load_config


@pytest.fixture(autouse=True)
def _no_real_llm_credentials(monkeypatch):
    """Structural guarantee that no test can make a real Anthropic API call.

    Every test that exercises the semantic matcher injects an explicit fake
    or Null LLMProvider rather than deriving one from the environment, so
    this is defense-in-depth rather than a currently-exploitable gap — but
    it makes "tests never touch the real API" true by construction instead
    of true by the absence of a bad test, regardless of what the runner's
    actual shell environment happens to have set.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(scope="session")
def real_config():
    """Loads the actual repo config/candidate files (the real candidate data).

    Using the real files (not synthetic fixtures) means these tests double
    as a regression check on the shipped candidate knowledge base itself.
    """
    return load_config()


@pytest.fixture(scope="session")
def real_profile(real_config):
    """The real, parsed CandidateProfile — shared across matching tests."""
    return parse_candidate_profile(real_config)


@pytest.fixture(scope="session")
def repo_root():
    return REPO_ROOT

from __future__ import annotations

import pytest

from job_agent.candidate.parser import parse_candidate_profile
from job_agent.config.loader import REPO_ROOT, load_config


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

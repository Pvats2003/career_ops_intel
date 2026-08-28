from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

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


# --------------------------------------------------------------------------
# Shared Playwright/local-HTTP-server fixtures for the browser-provider test
# suite (Phase 6D). Session-scoped and centralized here deliberately:
# Playwright's sync API only supports one active `sync_playwright()` context
# per process — two test modules each defining their own session-scoped
# `browser` fixture causes "Sync API inside the asyncio loop" errors when
# both run in the same pytest session, since the second `sync_playwright().
# start()` call happens while the first is still active. A single shared
# fixture here is the fix, not a style preference.
# --------------------------------------------------------------------------
BROWSER_PROVIDER_SITE_DIR = REPO_ROOT / "tests" / "fixtures" / "browser_provider" / "site"
BROWSER_PROVIDER_CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def _start_http_server(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def site_server():
    """Serves tests/fixtures/browser_provider/site/ on 127.0.0.1, an
    OS-assigned port. Shared by every browser-provider test module."""
    httpd, base_url = _start_http_server(BROWSER_PROVIDER_SITE_DIR)
    yield base_url
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="session")
def other_origin_server():
    """A second server instance for the same directory, bound to a
    different port — a different port is a different origin, used only
    by domain-drift tests."""
    httpd, base_url = _start_http_server(BROWSER_PROVIDER_SITE_DIR)
    yield base_url
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="session")
def browser():
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    if not Path(BROWSER_PROVIDER_CHROMIUM_EXECUTABLE).exists():
        pytest.skip("pre-installed Chromium not available in this environment")
    pw = playwright_sync_api.sync_playwright().start()
    b = pw.chromium.launch(headless=True, executable_path=BROWSER_PROVIDER_CHROMIUM_EXECUTABLE)
    yield b
    b.close()
    pw.stop()

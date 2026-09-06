"""Real-execution checkpoint — `find_submit_control()`: deterministic,
evidence-based identification of the one control that means "submit this
application". Pure read-only detection; never clicks. Every test runs
against local synthetic fixtures served on 127.0.0.1 — no real network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.applications.browser.session import BrowserSession
from job_agent.applications.browser.submit_control import find_submit_control

pytest.importorskip("playwright.sync_api")

CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)


def _url(site_server: str, fixture: str) -> str:
    return f"{site_server}/{fixture}"


def test_finds_the_single_real_submit_button(site_server, browser):
    with BrowserSession(_url(site_server, "submission_target.html"), browser=browser) as session:
        session.load()
        result = find_submit_control(session)
    assert result.control is not None
    assert result.control.label == "Submit Application"
    assert result.control.disabled is False


def test_finds_the_drivetrain_fixture_submit_button_too(site_server, browser):
    """Same detection logic must work against the existing Drivetrain
    native-HTML fixture -- proves this isn't tailored to one fixture's
    exact markup."""
    url = _url(site_server, "drivetrain_business_analyst_native.html")
    with BrowserSession(url, browser=browser) as session:
        session.load()
        result = find_submit_control(session)
    assert result.control is not None
    assert "submit" in result.control.label.lower()


def test_refuses_when_no_positive_match_exists(site_server, browser):
    """generic_native_form.html's only button has no submit-shaped text
    at all ("Submit Application" for the marked fixture's button, but the
    generic fixture uses different wording) -- check the actual fixture's
    button text is exercised correctly either way: this asserts the
    no-match path using a page with zero candidate buttons."""
    with BrowserSession(_url(site_server, "other_origin.html"), browser=browser) as session:
        session.load()
        result = find_submit_control(session)
    assert result.control is None
    assert "no control" in result.reason.lower()


ADVERSARIAL_FIXTURE = """<!DOCTYPE html>
<html><body>
<form>
  <button id="save-btn">Save</button>
  <button id="continue-btn">Continue</button>
  <button id="login-btn">Log In</button>
  <button id="cancel-btn">Cancel</button>
</form>
</body></html>
"""

MULTIPLE_SUBMIT_FIXTURE = """<!DOCTYPE html>
<html><body>
<form>
  <button id="submit-1">Submit Application</button>
  <button id="submit-2">Apply Now</button>
</form>
</body></html>
"""

DISABLED_SUBMIT_FIXTURE = """<!DOCTYPE html>
<html><body>
<form>
  <button id="submit-btn" disabled>Submit Application</button>
</form>
</body></html>
"""


@pytest.fixture()
def extra_fixture_dir():
    from job_agent.config.loader import REPO_ROOT

    return REPO_ROOT / "tests" / "fixtures" / "browser_provider" / "site"


def test_adversarial_page_with_only_non_submit_controls_refuses(
    site_server, browser, extra_fixture_dir
):
    name = "_tmp_adversarial_non_submit.html"
    path = extra_fixture_dir / name
    path.write_text(ADVERSARIAL_FIXTURE)
    try:
        with BrowserSession(_url(site_server, name), browser=browser) as session:
            session.load()
            result = find_submit_control(session)
        assert result.control is None
        assert "no control" in result.reason.lower()
    finally:
        path.unlink(missing_ok=True)


def test_multiple_submit_like_controls_refuses_ambiguity(
    site_server, browser, extra_fixture_dir
):
    name = "_tmp_multiple_submit.html"
    path = extra_fixture_dir / name
    path.write_text(MULTIPLE_SUBMIT_FIXTURE)
    try:
        with BrowserSession(_url(site_server, name), browser=browser) as session:
            session.load()
            result = find_submit_control(session)
        assert result.control is None
        assert "multiple plausible submit controls" in result.reason.lower()
    finally:
        path.unlink(missing_ok=True)


def test_disabled_submit_control_refuses(site_server, browser, extra_fixture_dir):
    name = "_tmp_disabled_submit.html"
    path = extra_fixture_dir / name
    path.write_text(DISABLED_SUBMIT_FIXTURE)
    try:
        with BrowserSession(_url(site_server, name), browser=browser) as session:
            session.load()
            result = find_submit_control(session)
        assert result.control is None
        assert "disabled" in result.reason.lower()
    finally:
        path.unlink(missing_ok=True)

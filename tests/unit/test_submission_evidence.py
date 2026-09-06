"""Real-execution checkpoint — `collect_post_submit_evidence()`: never
declares success from a click alone. Every test runs entirely against the
local synthetic `submission_target.html` -> `submission_success.html`
pair served on 127.0.0.1 — no real network, no real candidate data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.applications.browser.answer_planner import AnswerPlanner
from job_agent.applications.browser.filler import FormFiller
from job_agent.applications.browser.inspector import ApplicationFormInspector
from job_agent.applications.browser.session import BrowserSession
from job_agent.applications.browser.snapshot import build_snapshot
from job_agent.applications.browser.submission_evidence import collect_post_submit_evidence
from job_agent.applications.browser.submit_control import find_submit_control
from job_agent.applications.schema import GeneratedAnswer

pytest.importorskip("playwright.sync_api")

CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)

SYNTHETIC_VALUES = {
    "full_name": "Test Candidate",
    "email": "test.candidate@example.invalid",
    "phone": "+1-555-0100",
    "current_location": "Test City, Test Country",
    "current_company": "Synthetic Employer Inc.",
    "linkedin_url": "https://linkedin.com/in/testcandidate",
}

_LABELS = {
    "full_name": "Full name", "email": "Email", "phone": "Phone",
    "current_location": "Current location", "current_company": "Current company",
    "linkedin_url": "LinkedIn URL",
}


def _url(site_server: str) -> str:
    return f"{site_server}/submission_target.html"


def _fill(session: BrowserSession):
    snap = ApplicationFormInspector().inspect(session)
    from job_agent.applications.browser.field_mapper import DynamicFieldMapper

    questions = DynamicFieldMapper().to_questions(snap)
    by_text = {q.text: q for q in questions}

    def _answer(field_id: str) -> GeneratedAnswer:
        q = by_text[_LABELS[field_id]]
        return GeneratedAnswer(
            question=q.text, category=q.category, answer=SYNTHETIC_VALUES[field_id],
            confidence=0.99, source="test_synthetic", requires_human=False, validated=True,
        )

    answers = [_answer(fid) for fid in SYNTHETIC_VALUES]
    plans = AnswerPlanner().plan(snap.fields, answers)
    FormFiller(session).apply_plan(plans)
    return build_snapshot(
        session, job_id=1, company_name="Synthetic Co", title="Business Analyst",
    )


def test_click_navigate_confirm_produces_evidence(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snapshot = _fill(session)
        pre_submit_url = session.current_url

        result = find_submit_control(session)
        assert result.control is not None

        session.click_submit_control(result.control.selector)

        evidence = collect_post_submit_evidence(
            session, pre_submit_url=pre_submit_url, filled_snapshot=snapshot,
        )

    assert evidence is not None
    assert evidence.has_concrete_evidence
    assert "submission_success.html" in (evidence.confirmation_url or "")
    assert evidence.confirmation_text in (
        "thank you for your application",
        "we have received your application",
    )
    # The fixture's form uses method="get", so the raw post-click URL
    # carries every candidate field value in its query string --
    # confirmation_url must never retain that.
    assert "?" not in evidence.confirmation_url
    for value in SYNTHETIC_VALUES.values():
        assert value.lower() not in evidence.confirmation_url.lower()


def test_no_evidence_without_any_click(site_server, browser):
    """A page that never navigated and whose form is still present, with
    no confirmation text, must produce NO evidence -- "nothing happened"
    is not treated as ambiguous success."""
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snapshot = _fill(session)
        pre_submit_url = session.current_url
        evidence = collect_post_submit_evidence(
            session, pre_submit_url=pre_submit_url, filled_snapshot=snapshot,
        )
    assert evidence is None


def test_navigation_without_confirmation_text_is_not_enough_evidence(
    site_server, browser, tmp_path
):
    """Step 9: "page navigation occurred" must never be treated as
    success on its own -- a page that the form navigates to but that
    carries no confirmation-shaped wording (e.g. an error page, or an
    unrelated redirect) must produce NO evidence, even though the URL
    changed and the original form's fields are gone."""
    from job_agent.config.loader import REPO_ROOT

    site_dir = REPO_ROOT / "tests" / "fixtures" / "browser_provider" / "site"
    no_confirmation_page = site_dir / "_tmp_no_confirmation.html"
    no_confirmation_page.write_text(
        "<!DOCTYPE html><html><body><h1>Something else entirely</h1></body></html>"
    )
    target_page = site_dir / "_tmp_submission_no_confirmation.html"
    target_page.write_text(
        '<!DOCTYPE html><html><body><form action="_tmp_no_confirmation.html" '
        'method="get"><button type="submit" id="real-submit-button">'
        "Submit Application</button></form></body></html>"
    )
    try:
        with BrowserSession(
            f"{site_server}/_tmp_submission_no_confirmation.html", browser=browser
        ) as session:
            session.load()
            snapshot = build_snapshot(
                session, job_id=1, company_name="Synthetic Co", title="Business Analyst",
            )
            pre_submit_url = session.current_url
            result = find_submit_control(session)
            assert result.control is not None
            session.click_submit_control(result.control.selector)

            evidence = collect_post_submit_evidence(
                session, pre_submit_url=pre_submit_url, filled_snapshot=snapshot,
            )
        assert evidence is None
    finally:
        no_confirmation_page.unlink(missing_ok=True)
        target_page.unlink(missing_ok=True)

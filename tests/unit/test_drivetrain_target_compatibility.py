"""Phase 6D Stage 2 — offline compatibility check for the Drivetrain
"Business Analyst - Customer Platform" Lever posting
(https://jobs.lever.co/drivetrain/7c194c7d-4bbf-41cc-9dea-e0db2d2b2032/apply),
using a local synthetic fixture that mirrors ONLY the fields a human
manually observed and reported on that real page. This file never makes
a real network call, never contacts jobs.lever.co, and never uses real
personal data — every value filled into the DOM is an obvious synthetic
placeholder. Answer-generation truthfulness checks (test class below)
deliberately use the REAL, committed candidate profile as INPUT (the
same as every other test in this repo that imports `real_profile` from
conftest.py) — this only proves what the answer engine WOULD produce for
this candidate against this exact field set; nothing is ever filled into
a form or transmitted anywhere from those checks.

IMPORTANT SCOPE NOTE (see the full written report): `ApplicationFormInspector`
only discovers fields via the `data-field`/`data-label`/`data-required`
markers this fixture itself provides (its own module docstring says so
explicitly) — building this fixture with those markers proves the
DOWNSTREAM pipeline behaves correctly once fields are discovered. It does
NOT and cannot prove the real Drivetrain page's actual markup would be
discovered at all, since no generic real-world-markup heuristic exists in
this codebase yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.applications.answer_bank import load_answer_bank
from job_agent.applications.answer_engine import classify_question, generate_answer
from job_agent.applications.browser.answer_planner import AnswerPlanner
from job_agent.applications.browser.field_mapper import DynamicFieldMapper, question_text
from job_agent.applications.browser.filler import FormFiller
from job_agent.applications.browser.inspector import ApplicationFormInspector
from job_agent.applications.browser.session import BrowserSession
from job_agent.applications.browser.snapshot import build_snapshot
from job_agent.applications.schema import QuestionCategory
from job_agent.llm.provider import NullLLMProvider
from job_agent.resume.extractor import extract_resume_text

pytest.importorskip("playwright.sync_api")

FIXTURE_FILE = "drivetrain_business_analyst.html"
CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)

# `site_server` and `browser` are shared, session-scoped fixtures defined
# in tests/conftest.py — see that file for why they must not be redefined
# per-module (Playwright's sync API only supports one active
# sync_playwright() context per process).

EXPECTED_REQUIRED = {
    "full_name": True,
    "email": True,
    "phone": True,
    "current_location": True,
    "current_company": True,
    "linkedin_url": True,
}
EXPECTED_FIELD_IDS = {"resume", *EXPECTED_REQUIRED}

# Obvious synthetic placeholders only — never real personal data.
SYNTHETIC_VALUES = {
    "full_name": "Test Candidate",
    "email": "test.candidate@example.invalid",
    "phone": "+1-555-0100",
    "current_location": "Test City, Test Country",
    "current_company": "Test Company Inc.",
    "linkedin_url": "https://linkedin.com/in/testcandidate",
}


def _fixture_url(site_server: str) -> str:
    return f"{site_server}/{FIXTURE_FILE}"


# ==========================================================================
# 1-4, 7: field discovery/classification — given the fixture provides the
# required data-field markers (see module docstring's scope note).
# ==========================================================================
def test_resume_is_discovered_as_file_type(site_server, browser):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    resume = next(f for f in snap.fields if f.field_id == "resume")
    assert resume.input_type == "file"


def test_resume_required_flag_matches_what_was_actually_observed(site_server, browser):
    """The report did NOT mark Resume/CV as REQUIRED (unlike items 2-7) —
    this fixture faithfully mirrors that, rather than assuming every real
    ATS requires a resume."""
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    resume = next(f for f in snap.fields if f.field_id == "resume")
    assert resume.required is False


def test_all_six_reported_required_fields_are_classified_as_text_and_required(
    site_server, browser
):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    by_id = {f.field_id: f for f in snap.fields}
    for field_id, expected_required in EXPECTED_REQUIRED.items():
        assert by_id[field_id].input_type == "text", field_id
        assert by_id[field_id].required is expected_required, field_id


def test_linkedin_url_field_has_no_special_type_falls_to_text(site_server, browser):
    """ApplicationFormInspector._resolve_input_type has no branch for
    input type "url" — it falls through to the generic "text" case,
    exactly like every other non-textarea/select/checkbox/file input.
    This is not a bug (the rest of the pipeline treats it identically to
    any free-text field) but worth asserting explicitly rather than
    assuming."""
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    linkedin = next(f for f in snap.fields if f.field_id == "linkedin_url")
    assert linkedin.input_type == "text"


def test_exactly_the_seven_observed_fields_are_discovered_nothing_invented(site_server, browser):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    assert {f.field_id for f in snap.fields} == EXPECTED_FIELD_IDS


# ==========================================================================
# 5-6: no password/credential-shaped field can enter the snapshot path.
# This exact observed form has no password field, so these checks confirm
# absence rather than exercising a mitigation — see the written report for
# the separately-tracked, pre-existing gap this does NOT close.
# ==========================================================================
def test_no_field_in_this_observed_form_is_password_typed(site_server, browser):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    assert all(f.input_type != "password" for f in snap.fields)


def test_snapshot_contains_no_field_ids_beyond_what_was_observed(site_server, browser):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snapshot = build_snapshot(session, job_id=1, company_name="Drivetrain",
                                   title="Business Analyst - Customer Platform")
    snapshot_field_ids = {f.field_id for f in snapshot.fields}
    # build_snapshot excludes file fields by design (snapshot.py), so
    # "resume" is expected to be absent here, not a discrepancy.
    assert snapshot_field_ids == EXPECTED_FIELD_IDS - {"resume"}


# ==========================================================================
# 8: expected ApplicationQuestion representation.
# ==========================================================================
def test_to_questions_excludes_resume_includes_the_six_text_fields(site_server, browser):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    questions = DynamicFieldMapper().to_questions(snap)
    texts = {q.text for q in questions}
    assert texts == {
        "Full name", "Email", "Phone", "Current location",
        "Current company", "LinkedIn URL",
    }
    assert all(q.required for q in questions)


def test_linkedin_url_question_classifies_as_contact_category(site_server, browser):
    """Empirically verified, not assumed: answer_engine's keyword list
    for CONTACT includes the exact phrase "linkedin url", which matches
    this field's label verbatim."""
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    linkedin_field = next(f for f in snap.fields if f.field_id == "linkedin_url")
    assert classify_question(question_text(linkedin_field)) == QuestionCategory.CONTACT


def test_remaining_five_fields_do_not_match_any_known_keyword_category(site_server, browser):
    """Empirically verified finding, not an assumption: answer_engine's
    keyword lists are phrase-based ("email address", "phone number",
    "full legal name") and do not match a bare form-field label like
    "Email" or "Phone" — every one of these five falls through to
    QuestionCategory.CUSTOM. Not a crash or a fabrication risk (CUSTOM is
    a legitimate, handled category), but a real classification-coverage
    gap worth knowing about: these contact-shaped fields aren't
    recognized as CONTACT/PERSONAL by label alone."""
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    by_id = {f.field_id: f for f in snap.fields}
    for field_id in ("full_name", "email", "phone", "current_location", "current_company"):
        category = classify_question(question_text(by_id[field_id]))
        assert category == QuestionCategory.CUSTOM, f"{field_id} classified as {category}"


# ==========================================================================
# 9-10: answer-generation pipeline — real candidate profile as input,
# NullLLMProvider (no network call, matches conftest.py's autouse
# ANTHROPIC_API_KEY-stripping fixture), proving nothing is ever
# fabricated and everything unanswerable fails closed to HUMAN_REQUIRED.
# ==========================================================================
def test_answer_engine_never_fabricates_and_fails_closed_for_all_six_fields(
    site_server, browser, real_config, real_profile
):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    questions = DynamicFieldMapper().to_questions(snap)
    assert len(questions) == 6

    resume_text = extract_resume_text(real_config.env.candidate_dir / "resume_master.docx")
    bank = load_answer_bank(real_config.env.candidate_dir / "answers")

    for question in questions:
        answer = generate_answer(question, real_profile, resume_text, bank, NullLLMProvider())
        # No LLM is configured (NullLLMProvider always raises
        # LLMUnavailableError, exactly like this project's real shipped
        # state with no ANTHROPIC_API_KEY set) and no answer_bank entry
        # exists for any of these contact-identity fields (checked:
        # candidate/answers/*.md covers only narrative/behavioral
        # questions) — so every one of these six MUST fail closed.
        assert answer.answer is None, question.text
        assert answer.requires_human is True, question.text
        assert answer.source == "llm_unavailable", question.text


# ==========================================================================
# 11: the final Submit button remains completely outside the preparation
# path — both a static source check and a behavioral one.
# ==========================================================================
def test_no_source_file_references_the_real_submit_button():
    forbidden = ("real-submit-button", "SUBMIT APPLICATION")
    for path in Path("src/job_agent/applications/browser").glob("*.py"):
        source = path.read_text()
        for term in forbidden:
            assert term not in source, f"{path} references {term!r}"
    provider_source = Path(
        "src/job_agent/applications/providers/browser_application.py"
    ).read_text()
    for term in forbidden:
        assert term not in provider_source


def test_filling_with_synthetic_values_never_touches_the_submit_button(site_server, browser):
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
        questions = DynamicFieldMapper().to_questions(snap)
        by_text = {q.text: q for q in questions}

        from job_agent.applications.schema import GeneratedAnswer

        def _synth_answer(field_id: str) -> GeneratedAnswer:
            label = {
                "full_name": "Full name", "email": "Email", "phone": "Phone",
                "current_location": "Current location",
                "current_company": "Current company", "linkedin_url": "LinkedIn URL",
            }[field_id]
            q = by_text[label]
            return GeneratedAnswer(
                question=q.text, category=q.category, answer=SYNTHETIC_VALUES[field_id],
                confidence=0.99, source="test_synthetic", requires_human=False, validated=True,
            )

        answers = [_synth_answer(fid) for fid in SYNTHETIC_VALUES]
        plans = AnswerPlanner().plan(snap.fields, answers)
        result = FormFiller(session).apply_plan(plans)

        assert set(result.filled_field_ids) == set(SYNTHETIC_VALUES)

        snapshot = build_snapshot(session, job_id=1, company_name="Drivetrain",
                                   title="Business Analyst - Customer Platform")
        for field_id, expected_value in SYNTHETIC_VALUES.items():
            actual = next(f for f in snapshot.fields if f.field_id == field_id)
            assert actual.current_value == expected_value

        # The submit button itself must never have been clicked — still
        # on the same page, form still present, no navigation occurred.
        assert session.current_url == _fixture_url(site_server)
        submit_buttons = session.query_all("#real-submit-button")
        assert len(submit_buttons) == 1  # present, untouched


# ==========================================================================
# 12-13: existing applications-run behavior and safety gates unchanged.
# Zero-diff is proven at the report level (git diff against origin/main
# touches only new files); these are the static, in-repo confirmations.
# ==========================================================================
def test_cli_still_has_no_reference_to_this_target_or_browser_provider():
    source = Path("src/job_agent/cli/main.py").read_text()
    assert "drivetrain" not in source.lower()
    assert "BrowserApplicationProvider" not in source
    assert "provider = ManualReviewProvider()" in source

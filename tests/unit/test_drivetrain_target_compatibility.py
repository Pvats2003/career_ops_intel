"""Phase 6D Stage 2 — offline compatibility check for the Drivetrain
"Business Analyst - Customer Platform" Lever posting
(https://jobs.lever.co/drivetrain/7c194c7d-4bbf-41cc-9dea-e0db2d2b2032/apply),
using a local synthetic fixture that mirrors ONLY the fields a human
manually observed and reported on that real page. This file never makes
a real network call, never contacts jobs.lever.co, and never uses real
personal data — every value filled into the DOM is an obvious synthetic
placeholder. Answer-generation tests use `_synthetic_identity_profile()`
(a fully synthetic `CandidateProfile` built from `SYNTHETIC_VALUES`
below) — never the repository's real `candidate/profile.md` data or the
`real_profile` fixture — precisely so a test failure here can never print
real personal information into pytest output.

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

from job_agent.applications.answer_engine import classify_question, generate_answer
from job_agent.applications.browser.answer_planner import AnswerPlanner
from job_agent.applications.browser.field_mapper import DynamicFieldMapper, question_text
from job_agent.applications.browser.filler import FormFiller
from job_agent.applications.browser.inspector import ApplicationFormInspector
from job_agent.applications.browser.session import BrowserSession
from job_agent.applications.browser.snapshot import build_snapshot
from job_agent.applications.browser.snapshot_render import render_snapshot, snapshot_sections
from job_agent.applications.providers.browser_application import BrowserApplicationProvider
from job_agent.applications.rules_enforcement import evaluate_inspection
from job_agent.applications.schema import QuestionCategory
from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.llm.provider import NullLLMProvider

pytest.importorskip("playwright.sync_api")

FIXTURE_FILE = "drivetrain_business_analyst.html"
NATIVE_FIXTURE_FILE = "drivetrain_business_analyst_native.html"
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


def _fact(value: str) -> Fact[str]:
    return Fact[str](
        value=value, source="test_synthetic_profile", confidence=1.0, verified=True
    )


def _synthetic_identity_profile() -> CandidateProfile:
    """A fully synthetic CandidateProfile carrying only the obvious
    placeholder values already in SYNTHETIC_VALUES above -- built to
    prove the trusted-identity-fact resolver's behavior against THIS
    exact target's field labels without ever touching the repository's
    real candidate/profile.md data. A test failure against this profile
    can only ever print "Test Candidate"/"test.candidate@example.
    invalid"/etc. into pytest output, never a real name, email, phone,
    location, or LinkedIn URL."""
    unknown_pref = Fact.unknown(source="test_synthetic_profile")
    return CandidateProfile(
        identity_name=_fact(SYNTHETIC_VALUES["full_name"]),
        identity_current_location=_fact(SYNTHETIC_VALUES["current_location"]),
        contact_email=_fact(SYNTHETIC_VALUES["email"]),
        contact_phone=_fact(SYNTHETIC_VALUES["phone"]),
        contact_linkedin=_fact(SYNTHETIC_VALUES["linkedin_url"]),
        target_roles=TargetRoles(),
        work_preferences=WorkPreferences(
            remote=unknown_pref, willing_to_relocate=unknown_pref, notice_period=unknown_pref
        ),
        location_preferences=LocationPreferences(
            current_location=_fact(SYNTHETIC_VALUES["current_location"]),
            open_to_countries=unknown_pref,
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown_pref, minimum_annual=unknown_pref,
            target_annual=unknown_pref, negotiable=unknown_pref,
        ),
        visa_information=VisaInformation(
            nationality=unknown_pref, requires_sponsorship_us=unknown_pref,
            requires_sponsorship_uk=unknown_pref, requires_sponsorship_eu=unknown_pref,
            requires_sponsorship_other=unknown_pref,
        ),
    )


def _fixture_url(site_server: str) -> str:
    return f"{site_server}/{FIXTURE_FILE}"


def _native_fixture_url(site_server: str) -> str:
    return f"{site_server}/{NATIVE_FIXTURE_FILE}"


class _DrivetrainFakeJob:
    """Stands in for the real Job row. `company_name`/`title` are
    genuinely-established facts (the human-provided screenshots of the
    real posting), never invented; `id`/`application_url` never leave
    this local process."""

    id = 1
    company_name = "Drivetrain"
    title = "Business Analyst - Customer Platform"


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
# 9-10: answer-generation pipeline — a fully SYNTHETIC candidate profile
# as input (never real_profile/real candidate data — see
# _synthetic_identity_profile()), NullLLMProvider (no network call,
# matches conftest.py's autouse ANTHROPIC_API_KEY-stripping fixture).
# Proves the five trusted identity/contact labels resolve deterministically
# and "Current company" still fails closed to HUMAN_REQUIRED, without ever
# touching real candidate/profile.md data or being able to print real PII
# into pytest output on failure.
# ==========================================================================
def test_answer_engine_resolves_five_trusted_fields_and_fails_closed_for_current_company(
    site_server, browser
):
    """Phase 6D trusted-identity-fact update: five of these six labels
    ("Full name", "Email", "Phone", "Current location", "LinkedIn URL")
    now match `answer_engine._TRUSTED_IDENTITY_FACT_KEYWORDS` and resolve
    deterministically from a CandidateProfile's Fact[str] fields — never
    from the LLM (NullLLMProvider is passed and must never be reached for
    these five). "Current company" has no trusted-fact mapping and MUST
    still fail closed exactly as before. Every expected value compared
    below is one of the obvious SYNTHETIC_VALUES placeholders already
    defined at the top of this file — never real candidate data — so a
    failure here can only ever print a synthetic value."""
    with BrowserSession(_fixture_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    questions = DynamicFieldMapper().to_questions(snap)
    assert len(questions) == 6

    profile = _synthetic_identity_profile()
    trusted_mapping = {
        "Full name": ("identity_name", "full_name"),
        "Email": ("contact_email", "email"),
        "Phone": ("contact_phone", "phone"),
        "Current location": ("identity_current_location", "current_location"),
        "LinkedIn URL": ("contact_linkedin", "linkedin_url"),
    }

    for question in questions:
        answer = generate_answer(question, profile, "", [], NullLLMProvider())
        mapping = trusted_mapping.get(question.text)
        if mapping is not None:
            attr_name, synthetic_key = mapping
            assert answer.answer == SYNTHETIC_VALUES[synthetic_key], question.text
            assert answer.requires_human is False, question.text
            assert answer.source == f"candidate_fact:{attr_name}", question.text
        else:
            # "Current company" -- no trusted fact exists for it; must
            # still fail closed exactly as every field used to.
            assert question.text == "Current company", question.text
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
def test_cli_still_has_no_reference_to_this_specific_target():
    """No file/command in the CLI hardcodes the Drivetrain target
    specifically — Phase 6D Stage 2's `applications browser-preview`
    command (added after this test was first written) is fully generic,
    taking any --url the operator supplies; it legitimately does
    reference BrowserApplicationProvider (see test_cli_browser_preview.py),
    which is a separate, narrower invariant checked in
    test_browser_provider.py against `applications_run` specifically."""
    source = Path("src/job_agent/cli/main.py").read_text()
    assert "drivetrain" not in source.lower()


# ==========================================================================
# 14: full BrowserApplicationProvider pipeline against the native-HTML
# mirror -- the "next checkpoint" review snapshot for this target. Proves
# the ENTIRE, real, merged production path (discover -> inspect ->
# evaluate_inspection -> get_questions -> generate_answer -> fill ->
# get_snapshot) produces a correct, complete, non-fabricating
# HumanReviewSnapshot for this exact screenshot-derived field set,
# against the LOCAL fixture only -- jobs.lever.co is never contacted.
# The provider is deliberately constructed WITHOUT a resume_path, so even
# though the fixture has a file input, no upload is ever attempted.
# ==========================================================================
def test_full_provider_pipeline_produces_a_correct_non_fabricating_snapshot(
    site_server, browser, real_config
):
    """Uses a fully SYNTHETIC CandidateProfile (_synthetic_identity_profile())
    -- never real_profile/real candidate data. `real_config` is used only
    for `.rules` (config/rules.yaml's safety flags, not candidate data)."""
    url = _native_fixture_url(site_server)
    profile = _synthetic_identity_profile()
    job = _DrivetrainFakeJob()

    provider = BrowserApplicationProvider({job.id: url}, browser=browser)  # no resume_path

    target = provider.discover_application(job)
    assert target.reachable is True

    inspection = provider.inspect_application(job, target)
    assert inspection.structure_recognized is True
    assert inspection.captcha_detected is False
    assert inspection.mfa_detected is False
    assert inspection.consent_required is False

    verdict = evaluate_inspection(real_config.rules, inspection)
    assert verdict.human_required is False  # the FORM STRUCTURE is fine

    questions = provider.get_questions(job)
    assert len(questions) == 6  # resume (file) excluded, exactly the 6 text/URL fields

    answers = [generate_answer(q, profile, "", [], NullLLMProvider()) for q in questions]
    # Phase 6D: five of these six now resolve deterministically from the
    # synthetic, verified CandidateProfile facts -- never from the LLM/
    # answer bank. "Current company" has no trusted-fact mapping and must
    # still fail closed exactly as every field used to before this
    # checkpoint.
    field_id_to_synthetic_key = {
        "full_name": "full_name",
        "email": "email",
        "phone": "phone",
        "current_location": "current_location",
        "linkedin_url": "linkedin_url",
    }
    resolved_answers = [a for a in answers if not a.requires_human]
    unresolved_answers = [a for a in answers if a.requires_human]
    assert len(resolved_answers) == 5
    assert len(unresolved_answers) == 1
    assert unresolved_answers[0].question == "Current company"

    state = provider.fill_application(job, target, answers)
    assert state.answer_count == 5  # the five trusted fields were typed; current_company was not

    snapshot = provider.get_snapshot(job.id)
    assert snapshot is not None
    assert snapshot.company_name == "Drivetrain"
    assert snapshot.title == "Business Analyst - Customer Platform"
    assert snapshot.application_url == url  # honest: the LOCAL fixture, never the real URL
    assert snapshot.uploaded_files == ()  # resume never attached/uploaded

    expected_field_ids = set(EXPECTED_REQUIRED)
    assert {f.field_id for f in snapshot.fields} == expected_field_ids
    assert set(snapshot.required_field_ids) == expected_field_ids
    assert snapshot.optional_field_ids == ()
    assert set(snapshot.unresolved_field_ids) == {"current_company"}

    for field in snapshot.fields:
        assert field.required is True
        synthetic_key = field_id_to_synthetic_key.get(field.field_id)
        if synthetic_key is not None:
            # Compared against the same obvious SYNTHETIC_VALUES constant
            # used to build the profile -- never real candidate data.
            assert field.current_value == SYNTHETIC_VALUES[synthetic_key]
        else:
            assert field.field_id == "current_company"
            assert field.current_value == ""  # never filled, never fabricated

    # Rendering: the five resolved fields appear as proposed values; only
    # current_company lands in the unresolved list.
    sections = snapshot_sections(snapshot)
    assert {f.field_id for f in sections.proposed_fields} == set(field_id_to_synthetic_key)
    assert set(sections.unresolved_field_ids) == {"current_company"}


# ==========================================================================
# Phase 6D checkpoint — the complete local, end-to-end
# "prepare application -> HumanReviewSnapshot -> human-readable review
# output" demonstration this checkpoint exists to prove. Reuses exactly
# the same synthetic profile/fixture as the test above; adds what that
# test does not yet cover: explicit per-field trusted-fact PROVENANCE
# (the `GeneratedAnswer.source` string — the strongest existing
# provenance guarantee; `SnapshotField` itself carries no source
# metadata, and this checkpoint does not add any, per instruction), a
# full `render_snapshot()` pass (not just the structured
# `snapshot_sections()` data), and explicit no-password/no-upload proof.
# ==========================================================================
def test_local_end_to_end_prepare_to_human_review_snapshot_demonstration(
    site_server, browser, real_config
):
    """CandidateProfile -> trusted candidate facts -> answer resolution ->
    BrowserApplicationProvider -> synthetic application form -> prepared
    HumanReviewSnapshot -> human-readable review output, entirely local.
    Uses ONLY the synthetic `_synthetic_identity_profile()` -- never
    real_profile, never candidate/profile.md, never resume_master.docx."""
    url = _native_fixture_url(site_server)
    profile = _synthetic_identity_profile()
    job = _DrivetrainFakeJob()

    trusted_mapping = {
        "Full name": ("identity_name", "full_name"),
        "Email": ("contact_email", "email"),
        "Phone": ("contact_phone", "phone"),
        "Current location": ("identity_current_location", "current_location"),
        "LinkedIn URL": ("contact_linkedin", "linkedin_url"),
    }

    # 1-2: discover_application() / inspect_application()
    provider = BrowserApplicationProvider({job.id: url}, browser=browser)  # no resume_path
    target = provider.discover_application(job)
    assert target.reachable is True
    inspection = provider.inspect_application(job, target)
    assert inspection.structure_recognized is True
    assert inspection.captcha_detected is False
    assert inspection.mfa_detected is False

    # 3: evaluate_inspection() -- structure is fine, no hard-stop gate trips
    verdict = evaluate_inspection(real_config.rules, inspection)
    assert verdict.human_required is False

    # 4: get_questions()
    questions = provider.get_questions(job)
    assert len(questions) == 6  # resume (file) excluded

    # 5: generate answers using the actual answer-resolution stack --
    # NullLLMProvider proves the LLM is never invoked to manufacture
    # missing identity/contact data, and an empty answer bank proves
    # nothing is sourced from there either.
    answers = {
        a.question: a
        for a in (generate_answer(q, profile, "", [], NullLLMProvider()) for q in questions)
    }

    for label, (attr_name, synthetic_key) in trusted_mapping.items():
        answer = answers[label]
        assert answer.answer == SYNTHETIC_VALUES[synthetic_key], label
        assert answer.requires_human is False, label
        # Provenance: the strongest existing guarantee is GeneratedAnswer.
        # source -- SnapshotField carries no source metadata today, and
        # this checkpoint deliberately does not add any (no genuine
        # correctness gap requires it; see module-level note above).
        assert answer.source == f"candidate_fact:{attr_name}", label
        assert not answer.source.startswith("llm"), label
        assert not answer.source.startswith("answer_bank"), label

    current_company_answer = answers["Current company"]
    assert current_company_answer.answer is None
    assert current_company_answer.requires_human is True
    assert not current_company_answer.source.startswith("candidate_fact")

    # 6: fill_application() -- only the five trusted fields are ever typed
    state = provider.fill_application(job, target, list(answers.values()))
    assert state.answer_count == 5

    # 7: get_snapshot()
    snapshot = provider.get_snapshot(job.id)
    assert snapshot is not None
    assert snapshot.uploaded_files == ()  # Resume/CV: never uploaded, HUMAN_REQUIRED by omission
    assert all(f.field_type != "password" for f in snapshot.fields)  # no password anywhere
    assert set(snapshot.unresolved_field_ids) == {"current_company"}
    for attr_name, synthetic_key in trusted_mapping.values():
        field = next(f for f in snapshot.fields if f.field_id == synthetic_key)
        assert field.current_value == SYNTHETIC_VALUES[synthetic_key]
        # Provenance now flows all the way into the snapshot itself, not
        # just the intermediate GeneratedAnswer -- the same source
        # string, never recomputed.
        assert field.source == f"candidate_fact:{attr_name}"
    current_company_field = next(f for f in snapshot.fields if f.field_id == "current_company")
    assert current_company_field.current_value == ""  # never inferred, never fabricated
    assert current_company_field.source == ""  # no answer was ever associated with it

    # 8: render the HumanReviewSnapshot using the existing rendering path
    import io

    from rich.console import Console

    buf = io.StringIO()
    render_snapshot(snapshot, Console(file=buf, width=200))
    rendered = buf.getvalue()

    assert "Drivetrain" in rendered
    assert "Business Analyst - Customer Platform" in rendered
    assert "Needs your input" in rendered
    for _attr_name, synthetic_key in trusted_mapping.values():
        assert SYNTHETIC_VALUES[synthetic_key] in rendered  # proposed for fill
    assert SYNTHETIC_VALUES["current_company"] not in rendered  # never inferred/typed
    assert "current_company" in rendered  # disclosed as needing human input, never hidden
    assert "structurally unavailable" in rendered  # submission remains impossible
    # Every proposed value now carries explicit, human-readable provenance.
    assert rendered.count("Trusted candidate fact") == 5

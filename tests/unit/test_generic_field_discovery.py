"""Phase 6D Stage 2 — generic (non-`data-field`) form discovery in
`ApplicationFormInspector`. Proves the new heuristic path handles
ordinary, conventional HTML (native `<label for>`, wrapping `<label>`,
`aria-label`/`placeholder` fallback, name-grouped radios, native
`required`) without breaking the original `data-field`-marked path or
inventing an identifier for a field that has neither `id` nor `name`.

Every test here runs entirely against local synthetic fixtures served on
127.0.0.1 — no real network call, no real personal data (all filled
values, where used, are obvious synthetic placeholders).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.applications.browser.field_mapper import DynamicFieldMapper
from job_agent.applications.browser.inspector import ApplicationFormInspector
from job_agent.applications.browser.session import BrowserSession

pytest.importorskip("playwright.sync_api")

CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)

# `site_server` and `browser` are shared, session-scoped fixtures defined
# in tests/conftest.py.

GENERIC_FIXTURE = "generic_native_form.html"
DRIVETRAIN_MARKED_FIXTURE = "drivetrain_business_analyst.html"
DRIVETRAIN_NATIVE_FIXTURE = "drivetrain_business_analyst_native.html"

DRIVETRAIN_REQUIRED = {
    "resume": False,
    "full_name": True,
    "email": True,
    "phone": True,
    "current_location": True,
    "current_company": True,
    "linkedin_url": True,
}


def _url(site_server: str, fixture: str) -> str:
    return f"{site_server}/{fixture}"


def _inspect(site_server: str, browser, fixture: str):
    with BrowserSession(_url(site_server, fixture), browser=browser) as session:
        session.load()
        return ApplicationFormInspector().inspect(session)


# ==========================================================================
# generic_native_form.html — every label-resolution fallback exercised.
# ==========================================================================
def test_label_for_match_by_id(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    full_name = next(f for f in snap.fields if f.field_id == "full_name")
    assert full_name.label == "Full name"
    assert full_name.input_type == "text"
    assert full_name.required is True


def test_closest_label_wrap_for_textarea(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    bio = next(f for f in snap.fields if f.field_id == "bio")
    assert "Short bio" in bio.label
    assert bio.input_type == "textarea"
    assert bio.required is False


def test_closest_label_wrap_for_checkbox(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    newsletter = next(f for f in snap.fields if f.field_id == "newsletter")
    assert "newsletter" in newsletter.label.lower()
    assert newsletter.input_type == "checkbox"
    assert newsletter.is_consent is False


def test_placeholder_fallback_when_no_label_matches(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    nickname = next(f for f in snap.fields if f.field_id == "nickname")
    assert nickname.label == "Preferred nickname"
    assert nickname.required is False


def test_field_with_neither_id_nor_name_is_never_discovered(site_server, browser):
    """Never invented: a field this module cannot reliably re-select for
    filling is simply absent from the snapshot, not assigned a
    synthetic/unstable identifier."""
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    labels = {f.label for f in snap.fields}
    assert "Ignore me, I have no identity" not in labels
    # Exactly the nine addressable fields — nothing invented, nothing lost.
    # "tracking_id" (type="hidden") is deliberately absent: see
    # test_hidden_input_is_never_discovered below.
    assert {f.field_id for f in snap.fields} == {
        "full_name", "start_date", "bio", "newsletter", "nickname",
        "country", "contact_pref", "consent",
    }


def test_hidden_input_is_never_discovered(site_server, browser):
    """A type="hidden" input must never appear in discovered fields at
    all -- not filtered out after the fact, structurally excluded by the
    generic-path selector itself (_GENERIC_INPUT_EXCLUDED_TYPES). A real
    ATS embeds session/CSRF state in hidden inputs; treating one as a
    fillable "question" would be a correctness and safety bug, not a
    convenience gap."""
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    assert "tracking_id" not in {f.field_id for f in snap.fields}


def test_unrecognized_native_input_type_falls_back_to_generic_text(site_server, browser):
    """type="date" has no dedicated branch in _resolve_input_type -- it
    must fall through to the generic "text" classification safely
    (discovered, not dropped, not crashed on, not misclassified as
    something more sensitive like "password" or "file")."""
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    start_date = next(f for f in snap.fields if f.field_id == "start_date")
    assert start_date.input_type == "text"
    assert start_date.required is False


def test_native_select_discovered_with_options(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    country = next(f for f in snap.fields if f.field_id == "country")
    assert country.input_type == "select"
    assert country.required is True
    assert {o.value for o in country.options} == {"us", "ca"}


def test_native_radio_group_by_shared_name(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    radios = [f for f in snap.fields if f.field_id == "contact_pref"]
    assert len(radios) == 1  # grouped once, not once per <input>
    radio = radios[0]
    assert radio.input_type == "radio"
    assert radio.required is True
    option_texts = {o.text.strip() for o in radio.options}
    assert option_texts == {"Email", "Phone"}


def test_consent_keyword_heuristic_flags_terms_and_privacy_checkbox(site_server, browser):
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    consent = next(f for f in snap.fields if f.field_id == "consent")
    assert consent.input_type == "checkbox"
    assert consent.is_consent is True
    assert "consent" in snap.consent_fields


def test_generic_questions_map_cleanly_through_dynamic_field_mapper(site_server, browser):
    """The existing, unmodified DynamicFieldMapper needs no change to
    handle generically-discovered fields — proves the two paths converge
    on the same downstream representation."""
    snap = _inspect(site_server, browser, GENERIC_FIXTURE)
    questions = DynamicFieldMapper().to_questions(snap)
    texts = {q.text for q in questions}
    assert "Full name" in texts
    assert "Preferred nickname" in texts


# ==========================================================================
# Drivetrain native-HTML mirror — same field set, same required flags, as
# the data-field-marked version already proven in
# test_drivetrain_target_compatibility.py. This is the direct closure of
# the gap that compatibility check identified.
# ==========================================================================
def test_native_drivetrain_mirror_discovers_the_same_seven_fields(site_server, browser):
    snap = _inspect(site_server, browser, DRIVETRAIN_NATIVE_FIXTURE)
    assert {f.field_id for f in snap.fields} == set(DRIVETRAIN_REQUIRED)


def test_native_drivetrain_mirror_required_flags_match_the_marked_version(site_server, browser):
    snap = _inspect(site_server, browser, DRIVETRAIN_NATIVE_FIXTURE)
    by_id = {f.field_id: f for f in snap.fields}
    for field_id, expected_required in DRIVETRAIN_REQUIRED.items():
        assert by_id[field_id].required is expected_required, field_id


def test_native_drivetrain_mirror_resume_is_file_type(site_server, browser):
    snap = _inspect(site_server, browser, DRIVETRAIN_NATIVE_FIXTURE)
    resume = next(f for f in snap.fields if f.field_id == "resume")
    assert resume.input_type == "file"


def test_native_and_marked_drivetrain_mirrors_produce_the_same_question_set(site_server, browser):
    native_snap = _inspect(site_server, browser, DRIVETRAIN_NATIVE_FIXTURE)
    marked_snap = _inspect(site_server, browser, DRIVETRAIN_MARKED_FIXTURE)

    native_questions = {q.text for q in DynamicFieldMapper().to_questions(native_snap)}
    marked_questions = {q.text for q in DynamicFieldMapper().to_questions(marked_snap)}

    assert native_questions == marked_questions
    assert native_questions == {
        "Full name", "Email", "Phone", "Current location",
        "Current company", "LinkedIn URL",
    }


# ==========================================================================
# Backward compatibility: the original Stage 1 fixture (all data-field
# marked) must discover an identical field set through the two-path
# inspector as it did through the single-path original — no duplication,
# nothing newly invented from the generic path re-matching marked
# elements (the :not([data-field]) exclusion is what guarantees this).
# ==========================================================================
def test_marked_fixture_has_no_duplicate_or_generic_path_field_ids(site_server, browser):
    snap = _inspect(site_server, browser, "index.html")
    field_ids = [f.field_id for f in snap.fields]
    assert len(field_ids) == len(set(field_ids))  # no duplicates
    assert set(field_ids) == {
        "full_name", "email", "cover_letter", "salary_expectation", "country",
        "skills", "relocate", "which_locations", "willing_travel",
        "certifications", "resume", "consent",
        "otp_code",  # marked field inside the (hidden by default) MFA div
    }

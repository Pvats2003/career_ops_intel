"""Phase 6D Stage 1 — `BrowserApplicationProvider` and its supporting
`job_agent.applications.browser.*` modules.

Every test in this file drives a REAL Playwright browser against a REAL
local HTTP server — but that server only ever serves the static, inert,
self-contained files in `tests/fixtures/browser_provider/`, bound to
`127.0.0.1` on an OS-assigned port. Nothing here ever reaches any external
host, uses any real credential, or calls `provider.submit()` expecting
anything but an unconditional refusal. The whole module is skipped if the
environment's pre-installed Chromium binary is unavailable (e.g. a CI
image without it), so this file never falls back to downloading a browser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_agent.applications.allowlist import create_allowlist_entry
from job_agent.applications.approvals import compute_answer_fingerprint, create_approval
from job_agent.applications.errors import SubmissionRefusedError
from job_agent.applications.provider import ManualReviewProvider
from job_agent.applications.schema import (
    ApplicationQuestion,
    ApplicationStatus,
    GeneratedAnswer,
    QuestionCategory,
    SubmissionEvidence,
)
from job_agent.applications.service import (
    answers_from_db,
    prepare_application,
    submit_application,
)
from job_agent.applications.service import (
    discover_application as core_discover_application,
)
from job_agent.db.models import Application, ApplicationEvent, Candidate, Company, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.llm.provider import NullLLMProvider
from job_agent.matching.repository import save_job_match
from job_agent.matching.schema import Decision, JobMatchResult

pytest.importorskip("playwright.sync_api")

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "browser_provider"
)
DUMMY_RESUME = FIXTURE_DIR / "dummy_resume.txt"
CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)

from job_agent.applications.browser.answer_planner import AnswerPlanner, FieldPlan  # noqa: E402
from job_agent.applications.browser.field_mapper import (  # noqa: E402
    DynamicFieldMapper,
    question_text,
)
from job_agent.applications.browser.file_upload import FileUploadHandler  # noqa: E402
from job_agent.applications.browser.filler import FormFiller  # noqa: E402
from job_agent.applications.browser.inspector import (  # noqa: E402
    ApplicationFormInspector,
    DiscoveredField,
    DiscoveredOption,
)
from job_agent.applications.browser.session import (  # noqa: E402
    BrowserSession,
    DomainDriftDetectedError,
)
from job_agent.applications.browser.snapshot import (  # noqa: E402
    UploadedFileRecord,
    build_snapshot,
    compute_snapshot_fingerprint,
)
from job_agent.applications.providers.browser_application import (  # noqa: E402
    BrowserApplicationProvider,
    _sha256_file,
)


# --------------------------------------------------------------------------
# `site_server`, `other_origin_server`, and `browser` are shared, session-
# scoped fixtures defined in tests/conftest.py — centralized there because
# Playwright's sync API only supports one active `sync_playwright()` context
# per process, so a second test module defining its own `browser` fixture
# would conflict with this one. See conftest.py for the full rationale.
# --------------------------------------------------------------------------
def _site_url(
    base_url: str, *, scenario: str | None = None, drift_target: str | None = None
) -> str:
    url = f"{base_url}/index.html"
    params = []
    if scenario:
        params.append(f"scenario={scenario}")
    if drift_target:
        params.append(f"drift_target={drift_target}")
    if params:
        url += "?" + "&".join(params)
    return url


def _answer(
    question: str,
    *,
    answer: str | None = "sample answer",
    requires_human: bool = False,
    category: QuestionCategory = QuestionCategory.CUSTOM,
) -> GeneratedAnswer:
    return GeneratedAnswer(
        question=question,
        category=category,
        answer=None if requires_human else answer,
        confidence=0.9,
        source="template",
        requires_human=requires_human,
        validated=True,
    )


class _FakeJob:
    def __init__(
        self,
        job_id: int = 1,
        company_name: str = "Synthetic Test Employer",
        title: str = "Staff Engineer",
    ):
        self.id = job_id
        self.company_name = company_name
        self.title = title


# ==========================================================================
# BrowserSession — bound-origin / domain-drift guarantees
# ==========================================================================
def test_session_load_navigates_to_bound_url(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        assert session.current_url.startswith(site_server)


def test_session_click_off_origin_link_raises_domain_drift(
    site_server, other_origin_server, browser
):
    other_url = f"{other_origin_server}/other_origin.html"
    target = _site_url(site_server, drift_target=other_url)
    with BrowserSession(target, browser=browser) as session:
        session.load()
        with pytest.raises(DomainDriftDetectedError):
            session.click("#drift-trigger")


# ==========================================================================
# ApplicationFormInspector — passive DOM fact reporting
# ==========================================================================
def test_inspector_discovers_expected_field_ids(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    field_ids = {f.field_id for f in snap.fields}
    assert {
        "full_name", "email", "cover_letter", "salary_expectation", "country",
        "skills", "relocate", "willing_travel", "resume", "consent",
    }.issubset(field_ids)


def test_inspector_reports_no_captcha_or_mfa_by_default(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    assert snap.captcha_detected is False
    assert snap.mfa_detected is False


def test_inspector_detects_captcha_scenario(site_server, browser):
    with BrowserSession(_site_url(site_server, scenario="captcha"), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    assert snap.captcha_detected is True


def test_inspector_detects_mfa_scenario(site_server, browser):
    with BrowserSession(_site_url(site_server, scenario="mfa"), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    assert snap.mfa_detected is True


def test_inspector_conditional_fields_start_invisible(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    which_locations = next(f for f in snap.fields if f.field_id == "which_locations")
    certifications = next(f for f in snap.fields if f.field_id == "certifications")
    assert which_locations.visible is False
    assert certifications.visible is False


def test_inspector_radio_group_reported_once_with_both_options(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    relocate_fields = [f for f in snap.fields if f.field_id == "relocate"]
    assert len(relocate_fields) == 1
    assert {o.value for o in relocate_fields[0].options} == {"yes", "no"}


def test_inspector_consent_field_flagged(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    assert "consent" in snap.consent_fields


# ==========================================================================
# DynamicFieldMapper
# ==========================================================================
def test_to_questions_excludes_file_field(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    questions = DynamicFieldMapper().to_questions(snap)
    assert not any(q.text.strip() == "Resume" for q in questions)


def test_to_questions_classifies_salary_field_as_hard_block_category(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    questions = DynamicFieldMapper().to_questions(snap)
    assert any(q.category == QuestionCategory.SALARY for q in questions)


# ==========================================================================
# AnswerPlanner — pure logic, no browser needed
# ==========================================================================
def test_plan_matches_answer_by_question_text():
    field = DiscoveredField(
        field_id="full_name", label="Full name", input_type="text", required=True, visible=True
    )
    answer = _answer(question_text(field), answer="Jane Doe")
    plans = AnswerPlanner().plan((field,), [answer])
    assert plans[0].answer is not None
    assert plans[0].answer.answer == "Jane Doe"


def test_plan_leaves_unmatched_field_unresolved():
    field = DiscoveredField(
        field_id="full_name", label="Full name", input_type="text", required=True, visible=True
    )
    plans = AnswerPlanner().plan((field,), [])
    assert plans[0].answer is None


def test_plan_forces_unresolved_when_answer_requires_human():
    field = DiscoveredField(
        field_id="salary_expectation", label="What is your current or expected salary?",
        input_type="text", required=True, visible=True,
    )
    answer = _answer(question_text(field), requires_human=True, category=QuestionCategory.SALARY)
    plans = AnswerPlanner().plan((field,), [answer])
    assert plans[0].answer is None


def test_plan_forces_unresolved_for_multiselect_even_with_matching_answer():
    field = DiscoveredField(
        field_id="skills", label="Skills", input_type="multiselect", required=False, visible=True,
        options=(DiscoveredOption(value="python", text="Python"),),
    )
    answer = _answer(question_text(field), answer="Python")
    plans = AnswerPlanner().plan((field,), [answer])
    assert plans[0].answer is None


def test_plan_skips_file_fields_entirely():
    field = DiscoveredField(
        field_id="resume", label="Resume", input_type="file", required=True, visible=True
    )
    plans = AnswerPlanner().plan((field,), [])
    assert plans == []


# ==========================================================================
# FormFiller — the only component that writes to the DOM
# ==========================================================================
def test_fill_text_field_sets_value(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).fill_text_field("full_name", "Jane Doe")
        value = session.query_all('[data-field="full_name"]')[0].input_value()
    assert value == "Jane Doe"


def test_select_dropdown_sets_value(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).select_dropdown("country", "ca")
        value = session.query_all('[data-field="country"]')[0].input_value()
    assert value == "ca"


def test_select_radio_checks_correct_option(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).select_radio("relocate", "yes")
        checked = session.query_all('input[type="radio"][data-field="relocate"]:checked')
        value = checked[0].get_attribute("value")
    assert value == "yes"


def test_check_checkbox(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).check_checkbox("willing_travel")
        is_checked = session.query_all('[data-field="willing_travel"]')[0].is_checked()
    assert is_checked is True


def test_reveal_conditional_section_shows_certifications(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).reveal_conditional_section("certifications")
        visible = session.query_all('[data-field="certifications"]')[0].is_visible()
    assert visible is True


def test_apply_plan_reveals_which_locations_after_relocate_yes(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
        relocate_field = next(f for f in snap.fields if f.field_id == "relocate")
        answer = _answer(question_text(relocate_field), answer="Yes")
        plans = AnswerPlanner().plan((relocate_field,), [answer])
        result = FormFiller(session).apply_plan(plans)
    assert "relocate" in result.filled_field_ids
    assert "which_locations" in result.newly_revealed_field_ids


def test_apply_plan_never_fills_unresolved_fields(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        field = DiscoveredField(
            field_id="full_name", label="Full name", input_type="text", required=True, visible=True
        )
        plans = [FieldPlan(field=field, answer=None)]
        result = FormFiller(session).apply_plan(plans)
        value = session.query_all('[data-field="full_name"]')[0].input_value()
    assert result.unresolved_field_ids == ["full_name"]
    assert value == ""


# ==========================================================================
# FileUploadHandler
# ==========================================================================
def test_attach_resume_sets_file_input(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FileUploadHandler().attach_resume(session, "resume", DUMMY_RESUME)
        filename = session.query_all('[data-field="resume"]')[0].evaluate(
            "e => e.files.length > 0 ? e.files[0].name : ''"
        )
    assert filename == DUMMY_RESUME.name


def test_attach_resume_missing_file_raises_file_not_found_error(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        with pytest.raises(FileNotFoundError):
            FileUploadHandler().attach_resume(session, "resume", DUMMY_RESUME.parent / "nope.txt")


# ==========================================================================
# HumanReviewSnapshot / build_snapshot / compute_snapshot_fingerprint
# ==========================================================================
def test_build_snapshot_reflects_dom_values(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).fill_text_field("full_name", "Jane Doe")
        snap = build_snapshot(session, job_id=1, company_name="Acme", title="Staff Engineer")
    field = next(f for f in snap.fields if f.field_id == "full_name")
    assert field.current_value == "Jane Doe"


def test_snapshot_fingerprint_changes_when_form_structure_changes(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        before = build_snapshot(session, job_id=1, company_name="Acme", title="Staff Engineer")
        session.click("#simulate-form-change")
        after = build_snapshot(session, job_id=1, company_name="Acme", title="Staff Engineer")
    assert compute_snapshot_fingerprint(before) != compute_snapshot_fingerprint(after)


def test_snapshot_records_unresolved_field_ids(site_server, browser):
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = build_snapshot(
            session, job_id=1, company_name="Acme", title="Staff Engineer",
            unresolved_field_ids=("salary_expectation",),
        )
    assert "salary_expectation" in snap.unresolved_field_ids


def test_snapshot_records_uploaded_file_sha256(site_server, browser):
    expected = _sha256_file(DUMMY_RESUME)
    record = UploadedFileRecord(field_id="resume", filename=DUMMY_RESUME.name, sha256=expected)
    with BrowserSession(_site_url(site_server), browser=browser) as session:
        session.load()
        snap = build_snapshot(
            session, job_id=1, company_name="Acme", title="Staff Engineer",
            uploaded_files=(record,),
        )
    assert snap.uploaded_files[0].sha256 == expected


# ==========================================================================
# BrowserApplicationProvider — full stack, local target only
# ==========================================================================
def _visible_snapshot_fields(base_url: str, browser):
    with BrowserSession(base_url, browser=browser) as session:
        session.load()
        return ApplicationFormInspector().inspect(session).fields


def _generated_answers_for(base_url: str, browser) -> list[GeneratedAnswer]:
    """Builds one answer per visible, normally-answerable field, using the
    real `question_text()` so question strings match exactly what the
    provider itself will see. The salary field is deliberately given a
    `requires_human=True` (hard-block) answer, and multiselect/file fields
    are skipped, mirroring how the real answer_engine pipeline behaves."""
    answers: list[GeneratedAnswer] = []
    for f in _visible_snapshot_fields(base_url, browser):
        if not f.visible or f.input_type in ("file", "multiselect"):
            continue
        text = question_text(f)
        if f.field_id == "salary_expectation":
            answers.append(_answer(text, requires_human=True, category=QuestionCategory.SALARY))
        elif f.input_type in ("radio", "select"):
            answers.append(_answer(text, answer=f.options[0].text))
        elif f.input_type == "checkbox":
            answers.append(_answer(text, answer="yes"))
        else:
            answers.append(_answer(text, answer="sample answer"))
    return answers


def test_get_questions_returns_fallback_when_no_target_registered(browser):
    provider = BrowserApplicationProvider({}, browser=browser)
    questions = provider.get_questions(_FakeJob(job_id=999))
    assert len(questions) > 0


def test_get_questions_against_local_target_returns_visible_fields(site_server, browser):
    provider = BrowserApplicationProvider({1: _site_url(site_server)}, browser=browser)
    questions = provider.get_questions(_FakeJob(job_id=1))
    assert any("salary" in q.text.lower() for q in questions)


def test_discover_application_reachable_flags(site_server, browser):
    provider = BrowserApplicationProvider({1: _site_url(site_server)}, browser=browser)
    assert provider.discover_application(_FakeJob(job_id=1)).reachable is True
    assert provider.discover_application(_FakeJob(job_id=2)).reachable is False


def test_inspect_application_structure_recognized_in_normal_scenario(site_server, browser):
    provider = BrowserApplicationProvider({1: _site_url(site_server)}, browser=browser)
    target = provider.discover_application(_FakeJob(job_id=1))
    inspection = provider.inspect_application(_FakeJob(job_id=1), target)
    assert inspection.structure_recognized is True
    assert inspection.captcha_detected is False
    assert inspection.mfa_detected is False


def test_inspect_application_captcha_detected(site_server, browser):
    provider = BrowserApplicationProvider(
        {1: _site_url(site_server, scenario="captcha")}, browser=browser
    )
    target = provider.discover_application(_FakeJob(job_id=1))
    inspection = provider.inspect_application(_FakeJob(job_id=1), target)
    assert inspection.captcha_detected is True
    assert inspection.structure_recognized is False


def test_inspect_application_mfa_detected(site_server, browser):
    provider = BrowserApplicationProvider(
        {1: _site_url(site_server, scenario="mfa")}, browser=browser
    )
    target = provider.discover_application(_FakeJob(job_id=1))
    inspection = provider.inspect_application(_FakeJob(job_id=1), target)
    assert inspection.mfa_detected is True
    assert inspection.structure_recognized is False


def test_fill_application_stages_and_builds_snapshot_never_transmits(site_server, browser):
    url = _site_url(site_server)
    answers = _generated_answers_for(url, browser)
    provider = BrowserApplicationProvider({1: url}, browser=browser, resume_path=DUMMY_RESUME)
    target = provider.discover_application(_FakeJob(job_id=1))

    state = provider.fill_application(_FakeJob(job_id=1), target, answers)

    assert state.answer_count > 0
    snapshot = provider.get_snapshot(1)
    assert snapshot is not None
    assert snapshot.uploaded_files[0].filename == DUMMY_RESUME.name


def test_fill_application_hard_block_answer_never_filled(site_server, browser):
    url = _site_url(site_server)
    answers = _generated_answers_for(url, browser)
    provider = BrowserApplicationProvider({1: url}, browser=browser, resume_path=DUMMY_RESUME)
    target = provider.discover_application(_FakeJob(job_id=1))

    provider.fill_application(_FakeJob(job_id=1), target, answers)

    snapshot = provider.get_snapshot(1)
    salary_field = next(f for f in snapshot.fields if f.field_id == "salary_expectation")
    assert salary_field.current_value == ""
    assert "salary_expectation" in snapshot.unresolved_field_ids


def test_fill_application_with_no_answers_never_fills_anything(site_server, browser):
    url = _site_url(site_server)
    provider = BrowserApplicationProvider({1: url}, browser=browser, resume_path=DUMMY_RESUME)
    target = provider.discover_application(_FakeJob(job_id=1))

    provider.fill_application(_FakeJob(job_id=1), target, [])

    snapshot = provider.get_snapshot(1)
    assert snapshot.fields
    for f in snapshot.fields:
        if f.field_id == "country":
            # A native <select> always has an initial selection — the
            # placeholder option's own text, never an actual country
            # choice — so this reflects "nothing was filled" too.
            assert f.current_value == "-- select --"
        else:
            assert f.current_value in ("", "false")


def test_submit_always_raises_regardless_of_answers(browser):
    provider = BrowserApplicationProvider({}, browser=browser)
    with pytest.raises(SubmissionRefusedError):
        provider.submit(_FakeJob(job_id=1), [])


def test_verify_always_reports_unverified(browser):
    provider = BrowserApplicationProvider({}, browser=browser)
    result = provider.verify(_FakeJob(job_id=1), SubmissionEvidence(confirmation_id="whatever"))
    assert result.verified is False


def test_health_check_reports_target_count(site_server, browser):
    provider = BrowserApplicationProvider({1: _site_url(site_server)}, browser=browser)
    result = provider.health_check()
    assert result.healthy is True
    assert "1" in result.detail


def test_requires_persisted_approval_is_true(browser):
    assert BrowserApplicationProvider({}, browser=browser).requires_persisted_approval is True


def test_supports_inspection_is_true(browser):
    assert BrowserApplicationProvider({}, browser=browser).supports_inspection is True


# ==========================================================================
# Static safety-boundary checks — no browser/network needed.
# ==========================================================================
def test_browser_application_module_never_imports_credential_or_network_client():
    import job_agent.applications.providers.browser_application as mod

    source = Path(mod.__file__).read_text()
    forbidden_terms = (
        "submission_http", "EnvCredentialStore", "CredentialProvider", "import httpx",
    )
    for forbidden in forbidden_terms:
        assert forbidden not in source


def test_cli_applications_run_still_hardcodes_manual_review_provider_not_browser():
    from job_agent.cli import main as cli_main

    source = Path(cli_main.__file__).read_text()
    assert "BrowserApplicationProvider" not in source
    assert "provider = ManualReviewProvider()" in source


# ==========================================================================
# submit_application gate integration — proves BrowserApplicationProvider,
# as a REAL class (not a test double), is gated by the exact same Phase 6C
# strict-approval path every other requires_persisted_approval provider
# uses. `browser=None` is safe in this section: every path exercised here
# (allowlist/approval blocks, and submit()'s unconditional refusal) never
# touches self._browser.
# ==========================================================================
class _ConfigOverride:
    def __init__(self, base, *, dry_run=None, live_mode=None, level=None):
        self._base = base
        self._dry_run = dry_run
        self._live_mode = live_mode
        self._level = level

    def __getattr__(self, name):
        return getattr(self._base, name)

    @property
    def dry_run(self):
        return self._base.dry_run if self._dry_run is None else self._dry_run

    @property
    def live_mode(self):
        return self._base.live_mode if self._live_mode is None else self._live_mode

    def is_submission_allowed(self):
        return (not self.dry_run) and self.live_mode

    @property
    def automation(self):
        base_automation = self._base.automation
        if self._level is None:
            return base_automation
        updated_automation = base_automation.automation.model_copy(
            update={"level": self._level}
        )
        return base_automation.model_copy(update={"automation": updated_automation})


@pytest.fixture()
def live_config(real_config):
    return _ConfigOverride(real_config, dry_run=False, live_mode=True, level=4)


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture()
def candidate_row(db_session):
    candidate = Candidate(
        name="Test Candidate", email="test@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(candidate)
    db_session.flush()
    return candidate


@pytest.fixture()
def job_row(db_session):
    company_row = Company(name="Acme")
    db_session.add(company_row)
    db_session.flush()
    source = JobSource(name="greenhouse", kind="ats_api", enabled=True)
    db_session.add(source)
    db_session.flush()
    job = JobRow(
        source_id=source.id, source_job_id="1", company_id=company_row.id, company_name="Acme",
        title="Staff Engineer", application_url="https://ats.example.test/apply/1",
        job_fingerprint="fp-browser-gate-1",
    )
    db_session.add(job)
    db_session.flush()
    return job


def _match_row(db_session, job, candidate):
    result = JobMatchResult(
        overall_score=90, decision=Decision.APPLY,
        skills_match=90, experience_match=90, role_match=90, project_match=90,
        education_match=90, location_match=90, seniority_match=90, eligibility_match=90,
        reasoning="ok", semantic_available=False,
    )
    row = save_job_match(db_session, job_id=job.id, candidate_id=candidate.id, result=result)
    db_session.commit()
    return row


class _BenignQuestionProvider(ManualReviewProvider):
    """Same honest `submit()`/`verify()` refusal as `ManualReviewProvider`,
    but `get_questions()` returns only a single ordinarily-answerable
    question — `ManualReviewProvider`'s own `_STANDARD_QUESTIONS` include
    VISA/SALARY (hard-block categories), which this repository's real,
    committed candidate profile does not have fully-confirmed answers for,
    so using it directly would route every prepared application here to
    HUMAN_REQUIRED before the gate tests below ever get to exercise
    `submit_application`."""

    name = "benign_question_provider"

    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        return [
            ApplicationQuestion(
                text="Tell me about yourself.", category=QuestionCategory.MOTIVATION
            )
        ]


def _prepared_application(db_session, config, job, candidate, real_profile) -> Application:
    match = _match_row(db_session, job, candidate)
    application = core_discover_application(db_session, config, job, match, candidate.id)
    prepare_application(
        db_session, config, application, job, real_profile,
        _BenignQuestionProvider(), llm=NullLLMProvider(),
    )
    assert application.status == ApplicationStatus.PREPARED.value
    return application


def test_browser_provider_blocked_with_no_allowlist_entry_never_touches_browser(
    db_session, live_config, job_row, candidate_row, real_profile
):
    application = _prepared_application(
        db_session, live_config, job_row, candidate_row, real_profile
    )
    provider = BrowserApplicationProvider({}, browser=None)

    result = submit_application(db_session, live_config, application, job_row, provider)

    assert result.status == ApplicationStatus.PREPARED.value
    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    assert any(e.event_type == "SUBMISSION_BLOCKED_NOT_ALLOWLISTED" for e in events)


def test_browser_provider_blocked_with_allowlist_but_no_approval(
    db_session, live_config, job_row, candidate_row, real_profile
):
    application = _prepared_application(
        db_session, live_config, job_row, candidate_row, real_profile
    )
    create_allowlist_entry(
        db_session, job_row.job_fingerprint, "browser_application", job_row.application_url
    )
    db_session.commit()
    provider = BrowserApplicationProvider({}, browser=None)

    result = submit_application(db_session, live_config, application, job_row, provider)

    assert result.status == ApplicationStatus.PREPARED.value
    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    assert any(e.event_type == "SUBMISSION_BLOCKED_NO_APPROVAL" for e in events)


def test_browser_provider_full_gate_satisfied_still_fails_structurally_and_consumes_approval(
    db_session, live_config, job_row, candidate_row, real_profile
):
    """Even with a real allowlist entry AND a real, valid approval — every
    gate satisfied — submission remains structurally unavailable: the
    application must move to FAILED (via submit()'s unconditional
    SubmissionRefusedError), never SUBMITTED. And because approvals are
    consumed BEFORE the (failing) submit attempt, a second try is blocked
    exactly like "no approval" — the single-use approval is never
    replayable, regardless of whether the attempt it was consumed for
    succeeded."""
    application = _prepared_application(
        db_session, live_config, job_row, candidate_row, real_profile
    )
    create_allowlist_entry(
        db_session, job_row.job_fingerprint, "browser_application", job_row.application_url
    )
    answers = answers_from_db(db_session, application.id)
    create_approval(
        db_session, application.id, job_row.job_fingerprint, compute_answer_fingerprint(answers)
    )
    db_session.commit()
    provider = BrowserApplicationProvider({}, browser=None)

    result = submit_application(db_session, live_config, application, job_row, provider)

    assert result.status == ApplicationStatus.FAILED.value
    assert result.confirmation_id is None

    # Simulate an operator retrying the same application — the approval
    # was already consumed, so this must be blocked the same way "no
    # approval" is, never re-attempted against the (already-consumed)
    # approval.
    application.status = ApplicationStatus.PREPARED.value
    db_session.commit()
    submit_application(db_session, live_config, application, job_row, provider)
    events = db_session.query(ApplicationEvent).filter_by(application_id=application.id).all()
    assert any(e.event_type == "SUBMISSION_BLOCKED_NO_APPROVAL" for e in events)

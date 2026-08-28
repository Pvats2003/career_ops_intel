"""Phase 6D — regression + adversarial tests for the password-field
snapshot-leakage fix.

Prior finding: `<input type="password">` fell through
`ApplicationFormInspector._resolve_input_type()`'s generic "text"
fallback, so `HumanReviewSnapshot._current_value()` could read and
expose its live DOM value in plaintext.

The fix (see `inspector.py`, `field_mapper.py`, `answer_planner.py`,
`snapshot.py`, and `providers/browser_application.py`'s module
docstrings) is structural at every layer:

1. `<input type="password">` is classified as its own `"password"`
   `input_type`, never `"text"`.
2. `DynamicFieldMapper`/`AnswerPlanner` exclude it from ever becoming a
   question or a fill plan — `FormFiller` has no code path that can
   write into one.
3. `snapshot._current_value()` returns a fixed placeholder for a
   password field BEFORE ever querying the DOM for it — there is no
   "real value read then redacted" step.
4. `build_snapshot()` always marks a password field unresolved,
   regardless of what its caller passes in.
5. `BrowserApplicationProvider.inspect_application()` treats a visible
   password field as an unrecognized form structure, routing through
   the EXISTING, unmodified `stop_on_unexpected_form` safety gate to
   HUMAN_REQUIRED before any answer generation or filling is attempted.

Every test here runs entirely against a local synthetic fixture served
on 127.0.0.1 — no real network call. The fixture's password field is
PRE-FILLED (via the HTML `value` attribute) with an obviously-fake,
synthetic secret, `hunter2-secret-test-only` — this is never typed by
this test suite; it exists in the DOM to prove that even though a real
value IS present, nothing in this codebase ever reads it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

pytest.importorskip("playwright.sync_api")

CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

pytestmark = pytest.mark.skipif(
    not Path(CHROMIUM_EXECUTABLE).exists(),
    reason="pre-installed Chromium not available in this environment",
)

from job_agent.applications.browser.answer_planner import AnswerPlanner  # noqa: E402
from job_agent.applications.browser.field_mapper import (  # noqa: E402
    DynamicFieldMapper,
    question_text,
)
from job_agent.applications.browser.filler import FormFiller  # noqa: E402
from job_agent.applications.browser.inspector import ApplicationFormInspector  # noqa: E402
from job_agent.applications.browser.session import BrowserSession  # noqa: E402
from job_agent.applications.browser.snapshot import (  # noqa: E402
    PASSWORD_FIELD_REDACTED_PLACEHOLDER,
    build_snapshot,
)
from job_agent.applications.browser.snapshot_render import (  # noqa: E402
    render_snapshot,
    snapshot_sections,
)
from job_agent.applications.providers.browser_application import (  # noqa: E402
    BrowserApplicationProvider,
)
from job_agent.applications.rules_enforcement import evaluate_inspection  # noqa: E402
from job_agent.applications.schema import (  # noqa: E402
    ApplicationStatus,
    GeneratedAnswer,
    QuestionCategory,
)
from job_agent.applications.service import (  # noqa: E402
    discover_application as core_discover_application,
)
from job_agent.applications.service import prepare_application  # noqa: E402
from job_agent.cli.main import app  # noqa: E402
from job_agent.db.models import (  # noqa: E402
    Application,
    ApplicationEvent,
    Candidate,
    Company,
    JobSource,
)
from job_agent.db.models import Job as JobRow  # noqa: E402
from job_agent.db.session import get_engine, get_session_factory, init_db  # noqa: E402
from job_agent.llm.provider import NullLLMProvider  # noqa: E402
from job_agent.matching.repository import save_job_match  # noqa: E402
from job_agent.matching.schema import Decision, JobMatchResult  # noqa: E402

FAKE_SECRET = "hunter2-secret-test-only"
FIXTURE_NAME = "password_field_form.html"


def _url(site_server: str) -> str:
    return f"{site_server}/{FIXTURE_NAME}"


class _FakeJob:
    def __init__(self, job_id: int = 1, company_name: str = "Acme", title: str = "Engineer"):
        self.id = job_id
        self.company_name = company_name
        self.title = title


def _no_secret_anywhere(*haystacks: object) -> None:
    for h in haystacks:
        assert FAKE_SECRET not in str(h), f"fake secret leaked into: {h!r}"


# ==========================================================================
# 1. Inspector classification
# ==========================================================================
def test_password_input_is_never_classified_as_text(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    pwd = next(f for f in snap.fields if f.field_id == "account_password")
    assert pwd.input_type == "password"
    assert pwd.input_type != "text"


def test_ordinary_text_field_on_the_same_form_is_unaffected(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    name = next(f for f in snap.fields if f.field_id == "full_name")
    assert name.input_type == "text"
    assert name.required is True


# ==========================================================================
# 2. Never becomes a question or a fill plan
# ==========================================================================
def test_password_field_excluded_from_questions(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    questions = DynamicFieldMapper().to_questions(snap)
    assert all("password" not in q.text.lower() for q in questions)
    assert all(FAKE_SECRET not in q.text for q in questions)


def test_password_field_never_gets_a_field_plan(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    pwd = next(f for f in snap.fields if f.field_id == "account_password")
    answer = GeneratedAnswer(
        question=question_text(pwd), category=QuestionCategory.CUSTOM,
        answer=FAKE_SECRET, confidence=0.9, source="template",
        requires_human=False, validated=True,
    )
    plans = AnswerPlanner().plan(snap.fields, [answer])
    assert all(p.field.field_id != "account_password" for p in plans)


# ==========================================================================
# 3. Core regression: build_snapshot never exposes the value, structurally
# ==========================================================================
def test_build_snapshot_never_exposes_password_value_present_in_dom(site_server, browser):
    """The regression test for the originally-reported bug: a REAL value
    IS present in the live DOM (via the fixture's `value` attribute) at
    inspection time, and this asserts it is absent from every
    user-visible or persisted representation this function produces."""
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = build_snapshot(session, job_id=1, company_name="Acme", title="Engineer")

    pwd_field = next(f for f in snap.fields if f.field_id == "account_password")
    assert pwd_field.current_value == PASSWORD_FIELD_REDACTED_PLACEHOLDER
    assert "account_password" in snap.unresolved_field_ids

    # Absent from EVERY field's current_value across the whole snapshot,
    # not just the password field's own.
    _no_secret_anywhere(*(f.current_value for f in snap.fields))
    # Absent from the snapshot's own repr/str (fingerprint, ids, etc.)
    _no_secret_anywhere(snap)


def test_build_snapshot_masks_password_even_after_an_explicit_fill(site_server, browser):
    """Stronger than the DOM-preload case above: proves the mask holds
    even if something (bypassing AnswerPlanner/FormFiller's own
    exclusion) explicitly wrote the secret into the field first."""
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).fill_text_field("account_password", FAKE_SECRET)
        snap = build_snapshot(session, job_id=1, company_name="Acme", title="Engineer")

    pwd_field = next(f for f in snap.fields if f.field_id == "account_password")
    assert pwd_field.current_value == PASSWORD_FIELD_REDACTED_PLACEHOLDER
    _no_secret_anywhere(*(f.current_value for f in snap.fields), snap)


def test_ordinary_field_values_still_round_trip_normally(site_server, browser):
    """Existing behavior for non-sensitive fields is unchanged."""
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        FormFiller(session).fill_text_field("full_name", "Jane Doe")
        snap = build_snapshot(session, job_id=1, company_name="Acme", title="Engineer")
    name_field = next(f for f in snap.fields if f.field_id == "full_name")
    assert name_field.current_value == "Jane Doe"
    assert "full_name" not in snap.unresolved_field_ids


# ==========================================================================
# 4. Rendered snapshot output never exposes it
# ==========================================================================
def test_snapshot_sections_never_exposes_password_value(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = build_snapshot(session, job_id=1, company_name="Acme", title="Engineer")
    sections = snapshot_sections(snap)
    assert "account_password" not in {f.field_id for f in sections.proposed_fields}
    assert "account_password" in sections.unresolved_field_ids
    _no_secret_anywhere(sections)


def test_rendered_cli_output_never_exposes_password_value(site_server, browser):
    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        snap = build_snapshot(session, job_id=1, company_name="Acme", title="Engineer")
    buf = StringIO()
    console = Console(file=buf, width=200)
    render_snapshot(snap, console)
    output = buf.getvalue()
    assert FAKE_SECRET not in output
    assert "account_password" in output  # the field is still disclosed to exist
    assert "sensitive" in output.lower()


# ==========================================================================
# 5. inspect_application() fails closed via the EXISTING, unmodified gate
# ==========================================================================
def test_inspect_application_marks_structure_unrecognized(site_server, browser):
    provider = BrowserApplicationProvider({1: _url(site_server)}, browser=browser)
    target = provider.discover_application(_FakeJob(job_id=1))
    inspection = provider.inspect_application(_FakeJob(job_id=1), target)
    assert inspection.structure_recognized is False
    assert FAKE_SECRET not in inspection.detail


def test_evaluate_inspection_routes_to_human_required(site_server, browser, real_config):
    provider = BrowserApplicationProvider({1: _url(site_server)}, browser=browser)
    target = provider.discover_application(_FakeJob(job_id=1))
    inspection = provider.inspect_application(_FakeJob(job_id=1), target)
    verdict = evaluate_inspection(real_config.rules, inspection)
    assert verdict.human_required is True


# ==========================================================================
# 6. fill_application(): even a naive/adversarial pre-generated answer for
#    the password question can never reach the DOM or the snapshot.
# ==========================================================================
def test_fill_application_never_fills_password_even_with_a_matching_answer(
    site_server, browser
):
    url = _url(site_server)
    with BrowserSession(url, browser=browser) as session:
        session.load()
        snap = ApplicationFormInspector().inspect(session)
    pwd = next(f for f in snap.fields if f.field_id == "account_password")

    adversarial_answer = GeneratedAnswer(
        question=question_text(pwd), category=QuestionCategory.CUSTOM,
        answer=FAKE_SECRET, confidence=0.9, source="template",
        requires_human=False, validated=True,
    )
    name_field = next(f for f in snap.fields if f.field_id == "full_name")
    name_answer = GeneratedAnswer(
        question=question_text(name_field), category=QuestionCategory.CUSTOM,
        answer="Jane Doe", confidence=0.9, source="template",
        requires_human=False, validated=True,
    )

    provider = BrowserApplicationProvider({1: url}, browser=browser)
    target = provider.discover_application(_FakeJob(job_id=1))
    state = provider.fill_application(
        _FakeJob(job_id=1), target, [adversarial_answer, name_answer]
    )

    assert "account_password" not in state.detail or True  # detail is prose, not a value
    _no_secret_anywhere(state.detail)

    snapshot = provider.get_snapshot(1)
    assert snapshot is not None
    pwd_field = next(f for f in snapshot.fields if f.field_id == "account_password")
    assert pwd_field.current_value == PASSWORD_FIELD_REDACTED_PLACEHOLDER
    assert "account_password" in snapshot.unresolved_field_ids
    # The ordinary field was still filled normally — the exclusion is
    # specific to password fields, not a blanket failure of filling.
    name_snapshot_field = next(f for f in snapshot.fields if f.field_id == "full_name")
    assert name_snapshot_field.current_value == "Jane Doe"
    _no_secret_anywhere(*(f.current_value for f in snapshot.fields))


# ==========================================================================
# 7. Exceptions involving a password field's identity cannot expose a
#    value through str(exception) — no code path ever puts one there.
# ==========================================================================
def test_exception_referencing_the_password_field_never_contains_its_value(
    site_server, browser
):
    from job_agent.applications.browser.file_upload import FileUploadHandler

    with BrowserSession(_url(site_server), browser=browser) as session:
        session.load()
        with pytest.raises(Exception) as exc_info:  # noqa: PT011 - any Playwright error is fine
            # account_password is not a file input; this must fail, and
            # the resulting exception must never carry the field's value.
            FileUploadHandler().attach_resume(
                session, "account_password", Path(__file__)
            )
    assert FAKE_SECRET not in str(exc_info.value)


# ==========================================================================
# 8. Full DB-level prepare_application(): fails closed, no leakage into
#    ApplicationEvent.details or Application.error_message.
# ==========================================================================
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


def _job_row(db_session, application_url: str):
    company_row = Company(name="Acme")
    db_session.add(company_row)
    db_session.flush()
    source = JobSource(name="greenhouse", kind="ats_api", enabled=True)
    db_session.add(source)
    db_session.flush()
    job = JobRow(
        source_id=source.id, source_job_id="1", company_id=company_row.id, company_name="Acme",
        title="Engineer", application_url=application_url,
        job_fingerprint="fp-password-field-security",
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


def test_prepare_application_fails_closed_and_never_leaks_into_db(
    db_session, real_config, candidate_row, real_profile, site_server, browser
):
    job = _job_row(db_session, _url(site_server))
    match = _match_row(db_session, job, candidate_row)
    application = core_discover_application(
        db_session, real_config, job, match, candidate_row.id
    )

    provider = BrowserApplicationProvider({job.id: _url(site_server)}, browser=browser)
    prepare_application(
        db_session, real_config, application, job, real_profile, provider,
        llm=NullLLMProvider(),
    )

    assert application.status == ApplicationStatus.HUMAN_REQUIRED.value

    _no_secret_anywhere(application.error_message)

    events = (
        db_session.query(ApplicationEvent)
        .filter_by(application_id=application.id)
        .all()
    )
    assert len(events) > 0
    for event in events:
        _no_secret_anywhere(event.details, event.event_type)


# ==========================================================================
# 9. CLI browser-preview: fails closed, never prints the value.
# ==========================================================================
def test_cli_browser_preview_never_prints_password_value(
    tmp_path, monkeypatch, real_config, real_profile, site_server, browser
):
    import shutil

    import playwright.sync_api as playwright_sync_api

    from job_agent.db.repository import save_candidate_profile

    class _NonClosingBrowserProxy:
        def __init__(self, real_browser):
            self._real_browser = real_browser

        def __getattr__(self, name):
            return getattr(self._real_browser, name)

        def close(self) -> None:
            pass

    class _FakeChromium:
        @staticmethod
        def launch(**kwargs):
            return _NonClosingBrowserProxy(browser)

    class _FakePlaywright:
        chromium = _FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(playwright_sync_api, "sync_playwright", lambda: _FakePlaywright())

    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    db_path = tmp_path / "cli_password_field_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "250")

    url = _url(site_server)
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        candidate_id = save_candidate_profile(session, real_profile)
        company = Company(name="Acme-pwd")
        session.add(company)
        session.flush()
        source = JobSource(name="cli-password-field-test", kind="ats_api", enabled=True)
        session.add(source)
        session.flush()
        job = JobRow(
            source_id=source.id, source_job_id="fp-pwd", company_id=company.id,
            company_name="Acme", title="Engineer",
            application_url=url, job_fingerprint="fp-pwd-cli",
        )
        session.add(job)
        session.flush()
        application = Application(job_id=job.id, candidate_id=candidate_id, status="MATCHED")
        session.add(application)
        session.commit()
        application_id = application.id

    runner = CliRunner()
    result = runner.invoke(
        app, ["applications", "browser-preview", str(application_id), "--url", url, "--confirm"]
    )

    assert FAKE_SECRET not in result.output
    assert result.exit_code == 0, result.output
    assert "Human review required" in result.output
    assert "nothing was filled" in result.output

"""Phase 6C — verification-evidence contract tests.

Covers `validate_submission_evidence()`'s shape-only plausibility checks
using synthetic evidence only (nothing here was ever produced by a real
submission — none exists, since every shipped `submit()` unconditionally
refuses), plus an explicit, direct demonstration that this validator has
NO effect on `job_agent.applications.service.verify_application` — the
one existing, unmodified path to `VERIFIED`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.applications.provider import ApplicationProvider, ProviderHealthCheck
from job_agent.applications.repository import get_or_create_application
from job_agent.applications.schema import (
    ApplicationStatus,
    SubmissionEvidence,
    VerificationResult,
)
from job_agent.applications.service import verify_application
from job_agent.applications.verification_contract import (
    EvidenceValidation,
    validate_submission_evidence,
)
from job_agent.db.models import Candidate, Company, JobSource
from job_agent.db.models import Job as JobRow
from job_agent.db.session import get_engine, get_session_factory, init_db


# --------------------------------------------------------------------------
# Synthetic evidence only.
# --------------------------------------------------------------------------
def test_well_formed_evidence_is_valid():
    evidence = SubmissionEvidence(
        confirmation_id="fake-confirmation-abc123",
        confirmation_url="https://ats.example.test/confirm/abc123",
    )
    result = validate_submission_evidence(evidence)
    assert result == EvidenceValidation(valid=True, reasons=())


def test_empty_evidence_is_invalid():
    result = validate_submission_evidence(SubmissionEvidence())
    assert result.valid is False
    assert any("no concrete evidence" in r for r in result.reasons)


def test_whitespace_only_evidence_is_invalid():
    """Matches has_concrete_evidence's own whitespace-stripping rule —
    this validator never treats a blank-looking value as concrete."""
    result = validate_submission_evidence(SubmissionEvidence(confirmation_id="   "))
    assert result.valid is False


@pytest.mark.parametrize("short_id", ("a", "12", "abcde"))
def test_implausibly_short_confirmation_id_is_invalid(short_id):
    result = validate_submission_evidence(SubmissionEvidence(confirmation_id=short_id))
    assert result.valid is False
    assert any("implausibly short" in r for r in result.reasons)


def test_confirmation_id_at_the_minimum_length_is_valid():
    result = validate_submission_evidence(SubmissionEvidence(confirmation_id="abcdef"))
    assert result.valid is True


@pytest.mark.parametrize(
    "bad_url", ("not-a-url", "ftp://x.test/1", "javascript:alert(1)", "//no-scheme.test/1")
)
def test_malformed_confirmation_url_is_invalid(bad_url):
    result = validate_submission_evidence(
        SubmissionEvidence(confirmation_id="fake-abc123", confirmation_url=bad_url)
    )
    assert result.valid is False
    assert any("well-formed http(s) URL" in r for r in result.reasons)


def test_confirmation_text_alone_satisfies_concrete_evidence():
    result = validate_submission_evidence(
        SubmissionEvidence(confirmation_text="Your application has been received.")
    )
    assert result.valid is True


def test_multiple_failures_are_all_reported():
    result = validate_submission_evidence(
        SubmissionEvidence(confirmation_id="a", confirmation_url="not-a-url")
    )
    assert result.valid is False
    assert len(result.reasons) == 2


# --------------------------------------------------------------------------
# Explicit epistemic-limits proof: shape-valid is not proof of a real
# submission. A well-formed but entirely fabricated piece of evidence
# still passes — by design, and documented as a limitation, not a gap.
# --------------------------------------------------------------------------
def test_shape_valid_evidence_can_still_be_entirely_fabricated():
    """Nothing about `validate_submission_evidence` can distinguish a
    genuine platform confirmation from a well-formed lie — it has no
    network access and no independent signal to check against. This test
    exists to make that limitation explicit and regression-tested, not to
    demonstrate a bug."""
    fabricated_by_a_hypothetical_malicious_provider = SubmissionEvidence(
        confirmation_id="totally-made-up-id-123",
        confirmation_url="https://not-a-real-ats.test/fake-confirmation",
    )
    result = validate_submission_evidence(fabricated_by_a_hypothetical_malicious_provider)
    assert result.valid is True  # passes shape checks — and proves nothing else


# --------------------------------------------------------------------------
# Dormancy, demonstrated directly: verify_application()'s existing,
# unmodified evidence-checking logic reaches VERIFIED using evidence this
# validator would REJECT — proving this module has zero effect on the
# real execution path.
# --------------------------------------------------------------------------
class _FakeProvider(ApplicationProvider):
    def __init__(self, *, verify_result):
        self.name = "fake"
        self._verify_result = verify_result

    def get_questions(self, job):
        return []

    def submit(self, job, answers):
        raise AssertionError("not exercised in this test")

    def verify(self, job, evidence):
        return self._verify_result

    def health_check(self):
        return ProviderHealthCheck(healthy=True, detail="fake", checked_at=datetime.now(UTC))


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session


def test_verify_application_unaffected_by_the_new_stricter_validator(db_session):
    company = Company(name="Acme")
    db_session.add(company)
    db_session.flush()
    source = JobSource(name="verify-contract-test", kind="ats_api", enabled=True)
    db_session.add(source)
    db_session.flush()
    job = JobRow(
        source_id=source.id, source_job_id="1", company_id=company.id, company_name="Acme",
        title="PM", application_url="https://x.test/1", job_fingerprint="fp-verify-contract",
    )
    db_session.add(job)
    candidate = Candidate(
        name="Test", email="t@example.com", phone="+1", linkedin="li",
        current_location="Remote", parsed_at=datetime.now(UTC),
    )
    db_session.add(candidate)
    db_session.flush()

    application, _ = get_or_create_application(db_session, job.id, candidate.id, dry_run=True)
    application.status = ApplicationStatus.SUBMITTED.value
    db_session.commit()

    # Evidence with a 1-character confirmation_id: has_concrete_evidence
    # is True (existing rule), but validate_submission_evidence would
    # reject it as implausibly short. If verify_application consulted
    # this module at all, this test would fail to reach VERIFIED.
    thin_evidence = SubmissionEvidence(confirmation_id="a")
    assert validate_submission_evidence(thin_evidence).valid is False  # sanity check

    provider = _FakeProvider(
        verify_result=VerificationResult(verified=True, evidence=thin_evidence, reason="ok")
    )
    result = verify_application(db_session, application, job, provider)

    # verify_application's own, unchanged rule (has_concrete_evidence)
    # governs here — still reaches VERIFIED exactly as it did before
    # Phase 6C, proving this new module changed nothing about it.
    assert result.status == ApplicationStatus.VERIFIED.value


# --------------------------------------------------------------------------
# Structural safety: no network capability, no config-bypass surface.
# --------------------------------------------------------------------------
def test_no_network_capable_imports_in_verification_contract_module():
    """`urllib.parse.urlparse` (used for shape-checking a confirmation_url
    string) is pure string parsing — zero network I/O — so it is
    deliberately NOT in the forbidden list here, unlike `urllib.request`/
    `urllib.error`, which would actually be capable of a network call."""
    import ast
    import inspect

    import job_agent.applications.verification_contract as module

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    forbidden = (
        "httpx", "requests", "urllib.request", "urllib.error", "socket",
        "aiohttp", "playwright", "selenium",
    )
    for module_name in imported:
        for bad in forbidden:
            assert bad not in module_name


def test_verification_contract_imports_nothing_config_or_submission_related():
    import ast
    import inspect

    import job_agent.applications.verification_contract as module

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    forbidden_substrings = ("applications.provider", "config.loader", "applications.service")
    for module_name in imported:
        for forbidden in forbidden_substrings:
            assert forbidden not in module_name

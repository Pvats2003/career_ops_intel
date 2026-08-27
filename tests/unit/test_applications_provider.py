from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_agent.applications.errors import SubmissionRefusedError
from job_agent.applications.provider import (
    ApplicationProvider,
    ManualReviewProvider,
    ProviderHealthCheck,
)
from job_agent.applications.schema import (
    ApplicationQuestion,
    ApplicationTarget,
    GeneratedAnswer,
    QuestionCategory,
    SubmissionEvidence,
    VerificationResult,
)
from job_agent.db.models import Job as JobRow


@pytest.fixture()
def job() -> JobRow:
    job = JobRow(
        company_name="Acme",
        title="Associate Product Manager",
        application_url="https://x.test/1",
        job_fingerprint="fp1",
    )
    job.id = 1
    return job


class _LegacyProvider(ApplicationProvider):
    """Implements only the Phase 5 abstract methods — exactly what every
    concrete ApplicationProvider written before Phase 6A looked like.
    Proves the Phase 6A widening is backward-compatible: this class must
    still instantiate and its new inherited methods must still behave
    safely, without this class overriding a single one of them."""

    name = "legacy"

    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        return [
            ApplicationQuestion(
                text="Tell me about yourself.", category=QuestionCategory.MOTIVATION
            )
        ]

    def submit(self, job: JobRow, answers: list[GeneratedAnswer]) -> SubmissionEvidence:
        raise SubmissionRefusedError("legacy provider never submits")

    def verify(self, job: JobRow, evidence: SubmissionEvidence) -> VerificationResult:
        return VerificationResult(verified=False, evidence=None, reason="nothing to verify")

    def health_check(self) -> ProviderHealthCheck:
        return ProviderHealthCheck(healthy=True, detail="legacy", checked_at=datetime.now(UTC))


def test_get_questions_returns_representative_set_including_some_hard_block_categories(job):
    provider = ManualReviewProvider()
    questions = provider.get_questions(job)
    assert len(questions) > 0
    categories = {q.category for q in questions}
    from job_agent.applications.schema import HARD_BLOCK_CATEGORIES

    assert categories & HARD_BLOCK_CATEGORIES


def test_submit_always_refuses_never_fabricates_evidence(job):
    """The only production provider must never claim a submission succeeded
    — this is what makes real external submission structurally impossible
    in Phase 5."""
    provider = ManualReviewProvider()
    with pytest.raises(SubmissionRefusedError):
        provider.submit(job, answers=[])


def test_verify_never_confirms_since_nothing_was_ever_submitted(job):
    provider = ManualReviewProvider()
    evidence = SubmissionEvidence(confirmation_id="fake-id-should-not-matter")
    result = provider.verify(job, evidence)
    assert result.verified is False
    assert result.evidence is None


def test_health_check_reports_healthy_with_no_external_dependency():
    provider = ManualReviewProvider()
    check = provider.health_check()
    assert check.healthy is True


def test_provider_name_is_stable_identifier():
    assert ManualReviewProvider().name == "manual_review"


# --------------------------------------------------------------------------
# Phase 6A widened contract
# --------------------------------------------------------------------------
def test_legacy_provider_implementing_only_phase5_methods_still_instantiates(job):
    """The Phase 6A widening must not force every existing provider to
    implement new methods — the four added methods are concrete with safe
    defaults, not abstract."""
    provider = _LegacyProvider()
    assert provider.get_questions(job)


def test_legacy_provider_inherited_discover_application_is_conservative(job):
    target = _LegacyProvider().discover_application(job)
    assert isinstance(target, ApplicationTarget)
    assert target.job_id == job.id
    assert target.reachable is False  # never guesses reachability


def test_legacy_provider_inherited_inspect_application_defaults_unrecognized(job):
    target = _LegacyProvider().discover_application(job)
    inspection = _LegacyProvider().inspect_application(job, target)
    assert inspection.structure_recognized is False
    assert inspection.captcha_detected is False
    assert inspection.mfa_detected is False


def test_legacy_provider_inherited_retrieve_questions_delegates_to_get_questions(job):
    provider = _LegacyProvider()
    target = provider.discover_application(job)
    assert provider.retrieve_application_questions(job, target) == provider.get_questions(job)


def test_legacy_provider_inherited_fill_application_never_transmits(job):
    """fill_application must never call submit() or produce anything that
    looks like SubmissionEvidence — it only stages a count."""
    provider = _LegacyProvider()
    target = provider.discover_application(job)
    answers = [
        GeneratedAnswer(
            question="q", category=QuestionCategory.MOTIVATION, answer="a",
            confidence=0.9, source="answer_bank:x", requires_human=False, validated=True,
        )
    ]
    state = provider.fill_application(job, target, answers)
    assert state.answer_count == 1
    assert state.target_job_id == job.id
    assert not hasattr(state, "confirmation_id")


def test_manual_review_provider_discover_application_honest(job):
    target = ManualReviewProvider().discover_application(job)
    assert target.reachable is False
    assert "no real target discovery" in target.detail


def test_manual_review_provider_inspect_application_honest(job):
    target = ManualReviewProvider().discover_application(job)
    inspection = ManualReviewProvider().inspect_application(job, target)
    assert inspection.structure_recognized is False
    assert "no real structural inspection" in inspection.detail


def test_manual_review_provider_retrieve_application_questions_matches_get_questions(job):
    provider = ManualReviewProvider()
    target = provider.discover_application(job)
    assert (
        provider.retrieve_application_questions(job, target) == provider.get_questions(job)
    )


def test_manual_review_provider_fill_application_never_submits_or_transmits(job):
    provider = ManualReviewProvider()
    target = provider.discover_application(job)
    answers = [
        GeneratedAnswer(
            question="q", category=QuestionCategory.MOTIVATION, answer="a",
            confidence=0.9, source="answer_bank:x", requires_human=False, validated=True,
        )
    ]
    state = provider.fill_application(job, target, answers)
    assert state.answer_count == 1
    assert "human must fill and submit" in state.detail
    # fill_application must not have called submit() — submit() always
    # raises for this provider, so a raised exception here would prove it.


def test_provider_module_never_imports_core_decision_logic():
    """Architectural boundary from the Phase 6A spec, enforced
    automatically rather than only by convention: `job_agent.applications.
    provider` (and therefore every ApplicationProvider implementation
    living in it) must never import the state machine, the service layer,
    `transition_status`, or `AppConfig` — a provider has no way to decide
    submission eligibility or application status if it structurally
    cannot reach the code that decides them."""
    import ast
    import inspect

    import job_agent.applications.provider as provider_module

    source = inspect.getsource(provider_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    forbidden_substrings = (
        "applications.service",
        "applications.state_machine",
        "applications.rate_limits",
        "config.loader",
    )
    for module_name in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in module_name, (
                f"provider.py must never import {module_name!r} "
                f"(matches forbidden boundary {forbidden!r})"
            )


def test_manual_review_provider_still_never_submits_after_phase6a_widening(job):
    """The widened interface must not open any new path to a real
    submission — submit() is completely unchanged and still always
    refuses."""
    provider = ManualReviewProvider()
    target = provider.discover_application(job)
    provider.inspect_application(job, target)
    provider.retrieve_application_questions(job, target)
    state = provider.fill_application(job, target, answers=[])
    assert state.answer_count == 0
    with pytest.raises(SubmissionRefusedError):
        provider.submit(job, answers=[])

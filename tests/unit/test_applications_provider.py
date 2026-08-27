from __future__ import annotations

import pytest

from job_agent.applications.errors import SubmissionRefusedError
from job_agent.applications.provider import ManualReviewProvider
from job_agent.applications.schema import SubmissionEvidence
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

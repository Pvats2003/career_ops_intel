"""Follow-up message generator — Career OS FINAL GOD MODE Part 4.14.
Everything in the drafted message must trace back to real, already-known
facts (job title, company, days waiting, recruiter contact) — nothing
invented, and this module never sends anything itself."""

from __future__ import annotations

from job_agent.applications.follow_up import FollowUpRecommendation
from job_agent.applications.follow_up_message import generate_follow_up_message
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow


def _recommendation(**overrides) -> FollowUpRecommendation:
    application = ApplicationRow(
        job_id=1,
        candidate_id=1,
        pipeline_stage=overrides.pop("pipeline_stage", "APPLIED"),
        recruiter_contact=overrides.pop("recruiter_contact", None),
    )
    job = JobRow(
        company_name="Acme",
        title="Business Analyst",
        job_fingerprint="fp",
        freshness_status="NEW",
        lifecycle_status="ACTIVE",
    )
    base = dict(application=application, job=job, applied_days_ago=9, suggested_action="Follow up.")
    base.update(overrides)
    return FollowUpRecommendation(**base)


def test_message_references_real_job_title_and_company():
    message = generate_follow_up_message(_recommendation(), "Priya Sharma")
    assert "Business Analyst" in message.body
    assert "Acme" in message.body
    assert "Business Analyst" in message.subject


def test_message_states_the_actual_days_waited():
    message = generate_follow_up_message(_recommendation(applied_days_ago=14), "Priya Sharma")
    assert "14 days" in message.body


def test_message_signed_with_the_real_candidate_name():
    message = generate_follow_up_message(_recommendation(), "Priya Sharma")
    assert message.body.strip().endswith("Priya Sharma")


def test_greets_recruiter_by_name_when_known():
    message = generate_follow_up_message(
        _recommendation(recruiter_contact="Jane Doe"), "Priya Sharma"
    )
    assert message.body.startswith("Hi Jane Doe,")


def test_falls_back_to_generic_greeting_when_recruiter_unknown():
    message = generate_follow_up_message(_recommendation(recruiter_contact=None), "Priya Sharma")
    assert message.body.startswith("Hello,")


def test_stage_specific_wording_for_interview():
    message = generate_follow_up_message(
        _recommendation(pipeline_stage="INTERVIEW"), "Priya Sharma"
    )
    assert "after our interview" in message.body


def test_stage_specific_wording_for_assessment():
    message = generate_follow_up_message(
        _recommendation(pipeline_stage="ASSESSMENT"), "Priya Sharma"
    )
    assert "assessment" in message.body.lower()

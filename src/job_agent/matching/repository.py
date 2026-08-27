"""Persists JobMatchResult as a job_matches row.

Insert-only, deliberately: a job's match score can change over time (the
posting is edited, thresholds are retuned, the candidate profile changes),
and BUILD PROMPT section 53's audit-trail principle means each matching run
is its own historical record, not an overwrite of the last one. Analytics
(Phase 7+, section 24 — "which match score predicts interviews?") depends
on that history existing.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from job_agent.db.models import JobMatch
from job_agent.matching.schema import JobMatchResult


def save_job_match(
    session: Session, *, job_id: int, candidate_id: int, result: JobMatchResult
) -> JobMatch:
    row = JobMatch(
        job_id=job_id,
        candidate_id=candidate_id,
        overall_score=result.overall_score,
        decision=result.decision.value,
        skills_match=result.skills_match,
        experience_match=result.experience_match,
        role_match=result.role_match,
        project_match=result.project_match,
        education_match=result.education_match,
        location_match=result.location_match,
        seniority_match=result.seniority_match,
        eligibility_match=result.eligibility_match,
        missing_requirements=list(result.missing_requirements),
        concerns=list(result.concerns),
        hard_stop_reasons=list(result.hard_stop_reasons),
        excluded_reasons=list(result.excluded_reasons),
        semantic_available=result.semantic_available,
        reasoning=result.reasoning,
        prompt_version=result.prompt_version,
        model_used=result.model_used,
    )
    session.add(row)
    session.flush()
    return row

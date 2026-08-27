"""Orchestrates matching for jobs stored in the database against the
candidate profile — the `job-agent jobs match` entry point.

Cost-optimized per BUILD PROMPT section 40: the semantic (LLM) stage is
skipped entirely for jobs that are already decided by cheap, deterministic
signals alone — an excluded role/company or a hard-stop condition doesn't
need a "second opinion" from an LLM call, and a very low deterministic
score is exceedingly unlikely to be rescued by one either.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig
from job_agent.db.models import Job as JobRow
from job_agent.llm.provider import LLMProvider, NullLLMProvider
from job_agent.logging.setup import get_logger, log_event
from job_agent.matching.decision import finalize
from job_agent.matching.deterministic import JobText, compute_deterministic_match
from job_agent.matching.repository import save_job_match
from job_agent.matching.schema import Decision, JobMatchResult
from job_agent.matching.scoring import combine_match
from job_agent.matching.semantic import SemanticOutcome, run_semantic_match

logger = get_logger("job_agent.matching.service")

# Below this deterministic-only estimate, don't bother with an LLM call —
# see module docstring. Set well below save_threshold so a job that's only
# borderline-low still gets the semantic "second opinion" before SKIP.
_SEMANTIC_SKIP_SCORE = 30


@dataclass
class MatchOutcome:
    job_id: int
    title: str
    company: str
    result: JobMatchResult
    semantic_call_made: bool


def _job_text_from_row(row: JobRow) -> JobText:
    return JobText(
        title=row.title,
        company=row.company_name,
        description=row.description,
        requirements=row.requirements,
        preferred_qualifications=row.preferred_qualifications,
        location=row.location,
        remote_type=row.remote_type,
        employment_type=row.employment_type,
    )


def match_job(
    profile: CandidateProfile,
    config: AppConfig,
    job_row: JobRow,
    llm: LLMProvider,
) -> MatchOutcome:
    job_text = _job_text_from_row(job_row)
    deterministic = compute_deterministic_match(profile, config.profile, job_text)

    skip_semantic = bool(deterministic.excluded_reasons or deterministic.hard_stop_reasons)
    deterministic_estimate = (
        deterministic.skills_match
        + deterministic.role_match
        + deterministic.experience_match
        + deterministic.project_match
    ) / 4
    if deterministic_estimate < _SEMANTIC_SKIP_SCORE:
        skip_semantic = True

    if skip_semantic:
        reason = "skipped (excluded/hard-stop/very low deterministic score)"
        semantic = SemanticOutcome(available=False, unavailable_reason=reason)
        semantic_call_made = False
    else:
        semantic = run_semantic_match(llm, profile, job_text)
        semantic_call_made = semantic.available

    scored = combine_match(
        deterministic,
        semantic,
        weights=config.automation.scoring_weights,
        semantic_blend_weight=config.automation.matching.semantic_blend_weight,
    )
    result = finalize(scored, config.automation.matching)
    return MatchOutcome(
        job_id=job_row.id,
        title=job_row.title,
        company=job_row.company_name,
        result=result,
        semantic_call_made=semantic_call_made,
    )


def run_matching(
    session: Session,
    config: AppConfig,
    profile: CandidateProfile,
    candidate_id: int,
    llm: LLMProvider | None = None,
    job_ids: list[int] | None = None,
) -> list[MatchOutcome]:
    """Match the candidate against jobs in the database and persist results.

    `job_ids=None` matches every job currently in the `jobs` table. Pass an
    explicit list to match only specific jobs (e.g. newly discovered ones).
    """
    llm = llm or NullLLMProvider()
    query = select(JobRow)
    if job_ids is not None:
        query = query.where(JobRow.id.in_(job_ids))
    job_rows = list(session.execute(query).scalars())

    outcomes: list[MatchOutcome] = []
    for job_row in job_rows:
        try:
            outcome = match_job(profile, config, job_row, llm)
            save_job_match(
                session, job_id=job_row.id, candidate_id=candidate_id, result=outcome.result
            )
        except Exception as exc:  # noqa: BLE001
            # One malformed/unexpected job must never abort the whole batch —
            # at "thousands of jobs" scale, that would mean a single bad
            # posting silently loses every other job's match this run. The
            # failure is logged (not swallowed) and the job is simply left
            # unmatched this run; it remains eligible on the next `jobs match`.
            log_event(
                logger,
                component="matching.service",
                action="match_job",
                result="failure",
                job_id=job_row.id,
                title=job_row.title,
                company=job_row.company_name,
                error=str(exc),
            )
            continue
        outcomes.append(outcome)
    session.commit()
    return outcomes


__all__ = [
    "Decision",
    "MatchOutcome",
    "match_job",
    "run_matching",
]

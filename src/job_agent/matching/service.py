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
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.llm.provider import LLMProvider, NullLLMProvider
from job_agent.logging.setup import get_logger, log_event
from job_agent.matching.cache import compute_match_cache_key
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
        # Matching Engine V2: Arbeitnow is the one source that reports
        # visa_sponsorship as a verified per-listing fact (see
        # job_agent.jobs.sources.arbeitnow) — this used to be captured on
        # the Job row and then never actually read by the matcher.
        visa_information=row.visa_information,
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


def _outcome_from_cached_row(job_row: JobRow, row: JobMatchRow) -> MatchOutcome:
    """Rehydrates a `MatchOutcome` from an existing `JobMatch` row — used
    when `job_agent.matching.cache.compute_match_cache_key` says nothing
    that would change the result has changed since that row was written,
    so this run pays for NO deterministic recompute and NO LLM call
    (Phase 16 cost control)."""
    result = JobMatchResult(
        overall_score=int(row.overall_score),
        decision=Decision(row.decision),
        skills_match=int(row.skills_match or 0),
        experience_match=int(row.experience_match or 0),
        role_match=int(row.role_match or 0),
        project_match=int(row.project_match or 0),
        education_match=int(row.education_match or 0),
        location_match=int(row.location_match or 0),
        seniority_match=int(row.seniority_match or 0),
        eligibility_match=int(row.eligibility_match or 0),
        missing_requirements=tuple(row.missing_requirements or []),
        concerns=tuple(row.concerns or []),
        reasoning=row.reasoning or "",
        hard_stop_reasons=tuple(row.hard_stop_reasons or []),
        excluded_reasons=tuple(row.excluded_reasons or []),
        semantic_available=bool(row.semantic_available),
        prompt_version=row.prompt_version,
        model_used=row.model_used,
        # NULL on any row written before Matching Engine V2 — the score
        # itself is unaffected either way (raw_fit_score is display-only
        # supplementary evidence, not read by decide()/anything gating a
        # decision), and such a row's cache_key is already stale under
        # the bumped MATCH_LOGIC_VERSION, so it gets a real recompute
        # (with a real raw_fit_score) the moment matching runs again.
        raw_fit_score=(
            int(row.raw_fit_score) if row.raw_fit_score is not None else int(row.overall_score)
        ),
        risk_flags=tuple(row.risk_flags or []),
    )
    return MatchOutcome(
        job_id=job_row.id, title=job_row.title, company=job_row.company_name,
        result=result, semantic_call_made=False,
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

    Cost control (Phase 16): before doing any real work for a job, checks
    whether the LATEST existing `JobMatch` row for (job, candidate) was
    computed under an identical cache key (same job content, same profile,
    same scoring config — see `job_agent.matching.cache`). If so, that
    row is reused as-is and NO new deterministic/LLM work happens for
    that job this run — no new row is written either, since nothing about
    it would differ.
    """
    llm = llm or NullLLMProvider()
    query = select(JobRow)
    if job_ids is not None:
        query = query.where(JobRow.id.in_(job_ids))
    job_rows = list(session.execute(query).scalars())

    outcomes: list[MatchOutcome] = []
    for job_row in job_rows:
        try:
            cache_key = compute_match_cache_key(profile, config, job_row)
            existing = session.execute(
                select(JobMatchRow)
                .where(
                    JobMatchRow.job_id == job_row.id, JobMatchRow.candidate_id == candidate_id
                )
                .order_by(JobMatchRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if existing is not None and existing.cache_key == cache_key:
                outcomes.append(_outcome_from_cached_row(job_row, existing))
                continue

            outcome = match_job(profile, config, job_row, llm)
            save_job_match(
                session, job_id=job_row.id, candidate_id=candidate_id, result=outcome.result,
                cache_key=cache_key,
            )
            # Production-audit finding: this loop used to rely on the
            # single `session.commit()` after the whole batch below to
            # persist every job's match. `job_agent.jobs.service.
            # scan_source` already commits per-source rather than
            # accumulating the entire scan in one uncommitted
            # transaction — matching didn't follow the same pattern, so
            # a process interrupted partway through (e.g. a Render
            # free-plan container reclaimed mid-run) would silently roll
            # back EVERY job matched so far this run, not just the one
            # in flight, even though jobs discovered earlier in the same
            # search were already durably committed. Committing here
            # makes each job's match durable the moment it's computed;
            # cache_key already makes re-matching an already-matched job
            # a cheap no-op, so this changes nothing about a run that
            # completes normally.
            session.commit()
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

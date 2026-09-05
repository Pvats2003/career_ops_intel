"""End-to-end discovery run orchestration — Career OS Phase 8 section 3.

`execute_search_run` is the ONE place that chains: load search-query
portfolio -> scan enabled sources -> mark stale jobs expired -> match
against the candidate -> record a `SearchRun` row. It doesn't reimplement
any of those steps — `job_agent.jobs.query_generator.generate_search_
queries`, `job_agent.jobs.service.run_scan`/`mark_stale_jobs_expired`, and
`job_agent.matching.service.run_matching` are called exactly as `job-agent
jobs scan`/`jobs match` already call them; this module only adds the
orchestration and the persistent `SearchRun` audit record on top.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.candidate.schema import CandidateProfile
from job_agent.config.loader import AppConfig
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch as JobMatchRow
from job_agent.db.models import SearchPreferences as SearchPreferencesRow
from job_agent.db.models import SearchRun as SearchRunRow
from job_agent.jobs.notifications import generate_notifications
from job_agent.jobs.query_generator import generate_search_queries
from job_agent.jobs.service import mark_stale_jobs_expired, run_scan
from job_agent.jobs.source import JobSource
from job_agent.llm.provider import LLMProvider, NullLLMProvider
from job_agent.logging.setup import get_logger, log_event
from job_agent.matching.service import run_matching
from job_agent.resume.errors import ResumeExtractionError
from job_agent.resume.service import create_profile_version

logger = get_logger("job_agent.jobs.search_run")

_QUALIFIED_DECISIONS = frozenset({"APPLY", "REVIEW"})


def _count_fresh_duplicates(session: Session, since: datetime) -> int:
    """Among Job rows created during THIS run (created_at >= since), how
    many share a `job_fingerprint` with any other row (from this run or
    earlier) — i.e. how many of what was just discovered turned out to
    already be known under a different source. Read-only: this codebase
    deliberately never merges/drops cross-source duplicate rows (see
    `job_agent.jobs.repository`'s module docstring) — this is a count for
    reporting, not a mutation."""
    fresh_fingerprints = list(
        session.execute(
            select(JobRow.job_fingerprint).where(JobRow.created_at >= since)
        ).scalars()
    )
    if not fresh_fingerprints:
        return 0
    counts: dict[str, int] = {}
    for fp in session.execute(
        select(JobRow.job_fingerprint).where(JobRow.job_fingerprint.in_(fresh_fingerprints))
    ).scalars():
        counts[fp] = counts.get(fp, 0) + 1
    return sum(1 for fp in fresh_fingerprints if counts.get(fp, 1) > 1)


def _jobs_with_latest_matches(
    session: Session, job_ids: list[int], candidate_id: int
) -> list[tuple[JobRow, JobMatchRow | None]]:
    pairs: list[tuple[JobRow, JobMatchRow | None]] = []
    for job_id in job_ids:
        job = session.get(JobRow, job_id)
        if job is None:
            continue
        match = session.execute(
            select(JobMatchRow)
            .where(JobMatchRow.job_id == job_id, JobMatchRow.candidate_id == candidate_id)
            .order_by(JobMatchRow.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        pairs.append((job, match))
    return pairs


def execute_search_run(
    session: Session,
    config: AppConfig,
    profile: CandidateProfile,
    candidate_id: int,
    llm: LLMProvider | None = None,
    sources: list[JobSource] | None = None,
) -> SearchRunRow:
    """Runs one full discovery cycle and returns the persisted `SearchRun`
    row (already committed). Never raises for an ordinary source-level
    failure — those are captured in `SearchRun.errors` exactly like
    `ScanResult.errors` already are, and the run still completes for
    whatever sources DID succeed (BUILD PROMPT Phase 17: one failed
    source must not break the search). Only an unexpected, non-source
    error (e.g. a DB error) propagates, after the run is marked FAILED.

    `sources`, when given, bypasses `build_sources(config, ...)` entirely
    — the same escape hatch `job_agent.jobs.service.run_scan` already
    offers, used by tests to inject a source without a real config/
    network round-trip."""
    llm = llm or NullLLMProvider()
    started_at = datetime.now(UTC)
    portfolio = generate_search_queries(profile)

    run = SearchRunRow(
        started_at=started_at, sources=[], queries=list(portfolio.all_queries), status="RUNNING",
    )
    session.add(run)
    session.flush()
    session.commit()

    # Production-audit finding: `job-agent profile parse` (the only thing
    # that ever calls `create_profile_version`) is a CLI command — on a
    # deployment with no shell access (e.g. Render's free plan), it can
    # never run, so `CandidateProfileVersion` — and therefore the
    # dashboard's "Resume Status" — would stay permanently blank even
    # though the real resume is baked into the deployed image and parses
    # fine. `create_profile_version` is already idempotent (a no-op
    # returning the existing row when nothing about the profile/resume
    # changed since last time), so ensuring it here on every real search
    # run — the other place `CandidateDep`'s candidate/profile pipeline
    # already runs in the web app — costs nothing extra on repeat runs.
    # A missing/corrupt resume file must not block job discovery/matching
    # itself, so this is isolated in its own try/except rather than
    # folded into the main run below.
    try:
        create_profile_version(session, config, profile, candidate_id)
    except ResumeExtractionError as exc:
        log_event(
            logger, component="jobs.search_run", action="ensure_profile_version",
            result="failure", error=str(exc),
        )

    try:
        # Delegates the whole scan — including building the HTTP client,
        # building sources from it, and closing it — to `run_scan`, which
        # already keeps that client open for exactly as long as the sources
        # built from it are actually used. An earlier version duplicated
        # this lifecycle here and got it wrong: it closed the shared
        # `ResilientHttpClient` right after `build_sources()` returned
        # (which only constructs adapter objects — no network call happens
        # until they're scanned), so every real (non-test-injected) source
        # scan failed with "Cannot send a request, as the client has been
        # closed." — silently, in every real caller (CLI, web API, the
        # autonomous scheduler), never a single job found even with full
        # network access. Caught during a real-world activation audit.
        scan_results = run_scan(session, config, sources, queries=portfolio.all_queries)
        expired = mark_stale_jobs_expired(session)
        session.commit()

        match_outcomes = run_matching(session, config, profile, candidate_id, llm=llm)

        preferences = session.execute(
            select(SearchPreferencesRow).where(SearchPreferencesRow.candidate_id == candidate_id)
        ).scalar_one_or_none()
        min_score = preferences.notification_min_score if preferences is not None else 90
        touched_job_ids = [o.job_id for o in match_outcomes]
        jobs_with_matches = _jobs_with_latest_matches(session, touched_job_ids, candidate_id)
        generate_notifications(session, candidate_id, jobs_with_matches, min_score=min_score)

        run.sources = sorted({r.source_name for r in scan_results})
        run.jobs_found = sum(r.fetched for r in scan_results)
        run.duplicates_removed = _count_fresh_duplicates(session, started_at)
        run.expired_removed = expired
        run.qualified = sum(
            1 for o in match_outcomes if o.result.decision.value in _QUALIFIED_DECISIONS
        )
        run.errors = [e for r in scan_results for e in r.errors]
        run.status = "COMPLETED" if not run.errors else "PARTIAL"
        run.completed_at = datetime.now(UTC)
        session.commit()

        log_event(
            logger, component="jobs.search_run", action="execute_search_run",
            result="success", search_run_id=run.id, sources=run.sources,
            jobs_found=run.jobs_found, qualified=run.qualified,
            duplicates_removed=run.duplicates_removed, expired_removed=run.expired_removed,
            error_count=len(run.errors),
        )
        return run
    except Exception as exc:  # noqa: BLE001
        run.status = "FAILED"
        run.errors = [*run.errors, str(exc)]
        run.completed_at = datetime.now(UTC)
        session.commit()
        log_event(
            logger, component="jobs.search_run", action="execute_search_run",
            result="failure", search_run_id=run.id, error=str(exc),
        )
        raise

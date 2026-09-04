"""Orchestrates one discovery scan: build enabled sources from config, pull
postings, normalize, classify freshness, and persist with dedup.

This is the only place that wires `JobSource` implementations together with
the repository and config — adding a new source means registering it in
`build_sources()`, nothing else in this module changes (section 46).

Security fix (post-Phase-6A audit, remaining-sites pass): `ScanResult.
errors` is returned to `job-agent jobs scan`, which prints every entry to
the terminal verbatim (`cli/main.py`'s `jobs_scan` command) — a source
adapter's underlying HTTP client exception could in principle embed a
credential (a query-string API key, a Basic-auth header echoed back in an
error message) even though today's Greenhouse/Lever adapters use no
credentials at all. Both places that append to `result.errors` now scrub
through `job_agent.logging.setup.redact_text()` before the string is ever
stored — the same centralized boundary already used for `log_event()`,
`record_event()`, and the Phase 5/6A application-error paths, applied here
so `ScanResult.errors` protects its content by construction rather than
relying on the CLI (or a future caller) to remember to redact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.config.loader import AppConfig
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobSource as JobSourceRow
from job_agent.jobs.freshness import classify_freshness
from job_agent.jobs.repository import get_or_create_job_source, upsert_job
from job_agent.jobs.source import JobSource
from job_agent.jobs.sources.adzuna import AdzunaJobSource
from job_agent.jobs.sources.arbeitnow import ArbeitnowJobSource
from job_agent.jobs.sources.greenhouse import GreenhouseJobSource
from job_agent.jobs.sources.lever import LeverJobSource
from job_agent.jobs.sources.remotive import RemotiveJobSource
from job_agent.logging.setup import get_logger, log_event, redact_text
from job_agent.net.http_client import ResilientHttpClient

logger = get_logger("job_agent.jobs.service")


@dataclass
class ScanResult:
    source_name: str
    identifier: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    closed: int = 0
    errors: list[str] = field(default_factory=list)


def build_sources(
    config: AppConfig, http: ResilientHttpClient, queries: tuple[str, ...] = ()
) -> list[JobSource]:
    """Instantiate one adapter per configured, enabled board/source.

    `queries` (from `job_agent.jobs.query_generator.generate_search_
    queries(profile).all_queries` — the candidate's own generated search
    portfolio) drives the query-based sources (Remotive, Adzuna); it is
    optional and defaults to empty so callers with no candidate profile
    loaded (nothing currently requires one for a scan) simply get none of
    those instantiated — never a query-based source searching for an
    empty/guessed term. Arbeitnow needs no query at all (it lists every
    current posting) and is unaffected by this parameter.
    """
    sources: list[JobSource] = []

    gh_cfg = config.sources.sources.get("greenhouse")
    if gh_cfg and gh_cfg.enabled:
        for board in gh_cfg.boards:
            sources.append(GreenhouseJobSource(board.token, board.company_name, http))

    lever_cfg = config.sources.sources.get("lever")
    if lever_cfg and lever_cfg.enabled:
        for board in lever_cfg.boards:
            sources.append(LeverJobSource(board.token, board.company_name, http))

    remotive_cfg = config.sources.sources.get("remotive")
    if remotive_cfg and remotive_cfg.enabled:
        for term in queries[: remotive_cfg.max_queries]:
            sources.append(RemotiveJobSource(term, http))

    arbeitnow_cfg = config.sources.sources.get("arbeitnow")
    if arbeitnow_cfg and arbeitnow_cfg.enabled:
        sources.append(ArbeitnowJobSource(http))

    adzuna_cfg = config.sources.sources.get("adzuna")
    if adzuna_cfg and adzuna_cfg.enabled:
        app_id = config.env.adzuna_app_id
        app_key = config.env.adzuna_app_key
        if not app_id or not app_key:
            log_event(
                logger, component="jobs.service", action="build_sources",
                result="skipped", source="adzuna",
                reason="enabled but ADZUNA_APP_ID/ADZUNA_APP_KEY not set",
            )
        else:
            for country in adzuna_cfg.countries:
                for term in queries[: adzuna_cfg.max_queries]:
                    sources.append(AdzunaJobSource(country, term, app_id, app_key, http))

    return sources


def _identifier(source: JobSource) -> str:
    return (
        getattr(source, "board_token", None)
        or getattr(source, "company_slug", None)
        or getattr(source, "search_term", None)
        or getattr(source, "country", None)
        or "?"
    )


def scan_source(session: Session, config: AppConfig, source: JobSource) -> ScanResult:
    result = ScanResult(source_name=source.name, identifier=_identifier(source))
    source_cfg = config.sources.sources.get(source.name)
    kind = source_cfg.kind if source_cfg else "ats_api"
    source_row = get_or_create_job_source(session, name=source.name, kind=kind, enabled=True)

    # Health is derived from THIS scan's own search() outcome rather than
    # a separate health_check() probe call — the real operation the
    # pipeline just performed is a more accurate signal than a second,
    # extra network round-trip, and it costs nothing additional.
    checked_at = datetime.now(UTC)
    try:
        raw_postings = source.search()
    except Exception as exc:  # noqa: BLE001
        safe_error = redact_text(str(exc))
        result.errors.append(safe_error)
        source_row.last_health_check_at = checked_at
        source_row.last_health_status = f"unhealthy: {safe_error}"[:255]
        log_event(
            logger,
            component="jobs.service",
            action="scan_source",
            result="failure",
            source=source.name,
            identifier=result.identifier,
            error=safe_error,
        )
        session.commit()
        return result

    source_row.last_health_check_at = checked_at
    source_row.last_health_status = "healthy"
    source_row.last_success_at = checked_at

    result.fetched = len(raw_postings)
    seen_source_job_ids: set[str] = set()
    for raw in raw_postings:
        try:
            detailed = source.fetch_job(raw)
            job = source.normalize(detailed)
            seen_source_job_ids.add(job.source_job_id)
            freshness = classify_freshness(job.posted_at, settings=config.automation.freshness)
            _, was_created = upsert_job(
                session, job, source_row=source_row, freshness_status=freshness
            )
            if was_created:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            posting_id = raw.get("id", "?") if isinstance(raw, dict) else "?"
            result.errors.append(redact_text(f"posting {posting_id}: {exc}"))

    # Only run the "gone from this listing -> CLOSED" inference when the
    # scan actually returned at least one job — an empty result is far
    # more likely a degraded/rate-limited response than "this source
    # truly has zero open roles right now", and wrongly mass-closing
    # every previously-active job on a transient empty fetch would be
    # much worse than simply not updating lifecycle status this run.
    if raw_postings:
        result.closed = mark_missing_jobs_closed(session, source_row, seen_source_job_ids)

    session.commit()
    log_event(
        logger,
        component="jobs.service",
        action="scan_source",
        result="success" if not result.errors else "partial_failure",
        source=source.name,
        identifier=result.identifier,
        fetched=result.fetched,
        created=result.created,
        updated=result.updated,
        closed=result.closed,
        error_count=len(result.errors),
    )
    return result


def mark_missing_jobs_closed(
    session: Session, source_row: JobSourceRow, seen_source_job_ids: set[str]
) -> int:
    """A full re-scan of a source that previously returned ALL of that
    source's current jobs (every adapter in this codebase does — see each
    adapter's own docstring) implies any previously-ACTIVE job for this
    source NOT in this scan's results has been taken down. Conservative
    by construction: only ever moves ACTIVE -> CLOSED, never touches a
    job already CLOSED/EXPIRED, and only for rows belonging to this exact
    source (a job temporarily missing from one source's listing because
    it's cross-posted elsewhere is a different row entirely — see
    `job_agent.jobs.fingerprint`'s cross-source-dedup module docstring).
    Caller is responsible for only invoking this when `seen_source_job_ids`
    reflects a genuinely non-empty scan result (see `scan_source`)."""
    stale = session.execute(
        select(JobRow).where(
            JobRow.source_id == source_row.id,
            JobRow.lifecycle_status == "ACTIVE",
            JobRow.source_job_id.not_in(seen_source_job_ids),
        )
    ).scalars()
    closed = 0
    for job_row in stale:
        job_row.lifecycle_status = "CLOSED"
        closed += 1
    return closed


def mark_stale_jobs_expired(session: Session, *, max_active_days: int = 60) -> int:
    """A job still marked ACTIVE that hasn't been re-confirmed by any scan
    (`last_checked_at`) in `max_active_days` is presumed EXPIRED — covers
    the case `mark_missing_jobs_closed` can't (a source that stopped being
    scanned/enabled entirely, so no re-scan ever gets the chance to notice
    the posting disappeared). Never touches CLOSED/already-EXPIRED rows.
    Called once per full search run (`job_agent.jobs.search_run`), not
    per-source — staleness is source-agnostic."""
    cutoff = datetime.now(UTC) - timedelta(days=max_active_days)
    stale = session.execute(
        select(JobRow).where(JobRow.lifecycle_status == "ACTIVE", JobRow.last_checked_at < cutoff)
    ).scalars()
    expired = 0
    for job_row in stale:
        job_row.lifecycle_status = "EXPIRED"
        expired += 1
    return expired


def run_scan(
    session: Session,
    config: AppConfig,
    sources: list[JobSource] | None = None,
    *,
    queries: tuple[str, ...] = (),
) -> list[ScanResult]:
    """Run a full discovery scan across all enabled, configured sources.

    `queries` is forwarded to `build_sources` for the query-based sources
    (Remotive/Adzuna) — see that function's docstring. Ignored when an
    explicit `sources` list is passed (nothing to build).
    """
    limits = config.sources.global_limits
    http = ResilientHttpClient(
        max_retries=limits.max_retries_per_request,
        backoff_seconds=limits.default_backoff_seconds,
        backoff_multiplier=limits.default_backoff_multiplier,
        backoff_max_seconds=limits.default_backoff_max_seconds,
    )
    try:
        active_sources = (
            sources if sources is not None else build_sources(config, http, queries)
        )
        return [scan_source(session, config, src) for src in active_sources]
    finally:
        http.close()

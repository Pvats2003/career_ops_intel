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

from sqlalchemy.orm import Session

from job_agent.config.loader import AppConfig
from job_agent.jobs.freshness import classify_freshness
from job_agent.jobs.repository import get_or_create_job_source, upsert_job
from job_agent.jobs.source import JobSource
from job_agent.jobs.sources.greenhouse import GreenhouseJobSource
from job_agent.jobs.sources.lever import LeverJobSource
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
    errors: list[str] = field(default_factory=list)


def build_sources(config: AppConfig, http: ResilientHttpClient) -> list[JobSource]:
    """Instantiate one adapter per configured, enabled board."""
    sources: list[JobSource] = []

    gh_cfg = config.sources.sources.get("greenhouse")
    if gh_cfg and gh_cfg.enabled:
        for board in gh_cfg.boards:
            sources.append(GreenhouseJobSource(board.token, board.company_name, http))

    lever_cfg = config.sources.sources.get("lever")
    if lever_cfg and lever_cfg.enabled:
        for board in lever_cfg.boards:
            sources.append(LeverJobSource(board.token, board.company_name, http))

    return sources


def _identifier(source: JobSource) -> str:
    return getattr(source, "board_token", None) or getattr(source, "company_slug", None) or "?"


def scan_source(session: Session, config: AppConfig, source: JobSource) -> ScanResult:
    result = ScanResult(source_name=source.name, identifier=_identifier(source))
    source_cfg = config.sources.sources.get(source.name)
    kind = source_cfg.kind if source_cfg else "ats_api"
    source_row = get_or_create_job_source(session, name=source.name, kind=kind, enabled=True)

    try:
        raw_postings = source.search()
    except Exception as exc:  # noqa: BLE001
        safe_error = redact_text(str(exc))
        result.errors.append(safe_error)
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

    result.fetched = len(raw_postings)
    for raw in raw_postings:
        try:
            detailed = source.fetch_job(raw)
            job = source.normalize(detailed)
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
        error_count=len(result.errors),
    )
    return result


def run_scan(
    session: Session, config: AppConfig, sources: list[JobSource] | None = None
) -> list[ScanResult]:
    """Run a full discovery scan across all enabled, configured sources."""
    limits = config.sources.global_limits
    http = ResilientHttpClient(
        max_retries=limits.max_retries_per_request,
        backoff_seconds=limits.default_backoff_seconds,
        backoff_multiplier=limits.default_backoff_multiplier,
        backoff_max_seconds=limits.default_backoff_max_seconds,
    )
    try:
        active_sources = sources if sources is not None else build_sources(config, http)
        return [scan_source(session, config, src) for src in active_sources]
    finally:
        http.close()

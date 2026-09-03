"""Autonomous scheduled search — Career OS Phase 11 section 16.

`job-agent serve` starts a `BackgroundScheduler` (APScheduler) that polls
every `poll_minutes` (default 15) and, on each poll, checks whether it's
actually time to run a full search for the candidate — driven by
`SearchPreferences.search_frequency_hours` (Phase 15 settings, default
24h — "daily default, configurable") — and only then pays for a real
`execute_search_run`. This is intentionally a cheap poll-and-check loop
rather than one long-interval APScheduler job: it means a candidate
changing `search_frequency_hours` from the Settings page takes effect on
the very next poll, not after the previous (now-stale) interval finishes.

Never started implicitly by `job_agent.web.app.create_app()` — tests call
that dozens of times per run, and a background thread per call would leak.
Only `job-agent serve` opts in, and only when `--scheduler` isn't disabled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from job_agent.candidate.parser import parse_candidate_profile
from job_agent.config.loader import AppConfig
from job_agent.db.models import SearchPreferences as SearchPreferencesRow
from job_agent.db.models import SearchRun as SearchRunRow
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.search_run import execute_search_run
from job_agent.llm.provider import build_llm_provider
from job_agent.logging.setup import get_logger, log_event

logger = get_logger("job_agent.jobs.scheduler")

_DEFAULT_FREQUENCY_HOURS = 24


def _is_due(session, candidate_id: int) -> bool:
    preferences = session.execute(
        select(SearchPreferencesRow).where(SearchPreferencesRow.candidate_id == candidate_id)
    ).scalar_one_or_none()
    frequency_hours = (
        preferences.search_frequency_hours if preferences is not None else _DEFAULT_FREQUENCY_HOURS
    )

    last_run = session.execute(
        select(SearchRunRow)
        .where(SearchRunRow.status.in_(("COMPLETED", "PARTIAL")))
        .order_by(SearchRunRow.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if last_run is None or last_run.completed_at is None:
        return True

    completed_at = last_run.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - completed_at >= timedelta(hours=frequency_hours)


def run_scheduled_search_tick(config: AppConfig) -> None:
    """One scheduler poll. Never raises — a scheduler thread that dies on
    the first transient error would silently stop all future autonomous
    searches, so every failure is logged and swallowed here (the same
    posture `execute_search_run` already takes for individual sources)."""
    try:
        engine = get_engine(config.env.database_url)
        init_db(engine)
        session_factory = get_session_factory(engine)
        with session_factory() as session:
            profile = parse_candidate_profile(config)
            candidate_id = save_candidate_profile(session, profile)
            session.commit()

            if not _is_due(session, candidate_id):
                return

            llm = build_llm_provider(config)
            execute_search_run(session, config, profile, candidate_id, llm=llm)
            log_event(
                logger, component="jobs.scheduler", action="run_scheduled_search_tick",
                result="success", candidate_id=candidate_id,
            )
    except Exception as exc:  # noqa: BLE001
        log_event(
            logger, component="jobs.scheduler", action="run_scheduled_search_tick",
            result="failure", error=str(exc),
        )


def build_scheduler(config: AppConfig, *, poll_minutes: int = 15) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_search_tick,
        "interval",
        minutes=poll_minutes,
        args=[config],
        id="career_os_scheduled_search",
        next_run_time=datetime.now(UTC),  # also fire once immediately on startup
    )
    return scheduler

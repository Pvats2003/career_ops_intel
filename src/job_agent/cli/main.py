"""job-agent CLI.

Phase 1 implements: init, profile parse, status, health.
Phase 2 adds: jobs scan.
Phase 3 adds: jobs match.
Phase 4 adds: profile parse now also snapshots a validated, versioned
profile (candidate_profile_versions); profile history lists past versions.
Phase 5 adds: applications prepare/review/run (dry-run by default; no real
ATS integration exists yet, so `run` always reports what a human still
needs to do rather than actually submitting anything).
Phase 6A (architecture/contracts only — no real provider, no real
submission) adds per-item failure isolation to `applications prepare`/
`applications run`: one job/application raising an unexpected error is
logged and skipped, never aborting the rest of the batch.
Later-phase commands are registered now (so the interface contract is
stable) but exit with a clear "not implemented yet" message rather than
pretending to do something they can't — see BUILD PROMPT section 48.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.applications.allowlist import (
    create_allowlist_entry,
    revoke_allowlist_entry,
)
from job_agent.applications.answer_bank import load_answer_bank
from job_agent.applications.answer_engine import generate_answer
from job_agent.applications.approvals import (
    compute_answer_fingerprint,
    consume_approval,
    create_approval,
    get_valid_approval,
)
from job_agent.applications.browser.snapshot import (
    HumanReviewSnapshot,
    compute_snapshot_fingerprint,
)
from job_agent.applications.browser.snapshot_render import render_snapshot
from job_agent.applications.errors import ProviderError
from job_agent.applications.human_input import (
    HUMAN_INPUT_SOURCE_PREFIX,
    apply_human_input_overrides,
)
from job_agent.applications.provider import ManualReviewProvider
from job_agent.applications.providers.browser_application import BrowserApplicationProvider
from job_agent.applications.repository import (
    get_answers,
    get_latest_event,
    get_or_create_application,
    record_event,
)
from job_agent.applications.rules_enforcement import evaluate_inspection
from job_agent.applications.schema import ApplicationStatus, GeneratedAnswer
from job_agent.applications.service import (
    answers_from_db,
    build_application_provider,
    prepare_applications_batch,
    submit_application,
    submit_applications_batch,
    verify_application,
)
from job_agent.applications.state_machine import IllegalStateTransitionError
from job_agent.candidate.parser import CandidateParseError, parse_candidate_profile
from job_agent.config.loader import REPO_ROOT, AppConfig, load_config
from job_agent.db.models import Application, ApplicationAllowlistEntry, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.repository import get_or_create_job_source, upsert_job
from job_agent.jobs.schema import FreshnessStatus
from job_agent.jobs.schema import Job as JobTargetSchema
from job_agent.jobs.service import run_scan
from job_agent.llm.provider import NullLLMProvider, build_llm_provider
from job_agent.logging.setup import configure_logging, get_logger, log_event, redact_text
from job_agent.matching.service import run_matching
from job_agent.resume.errors import ResumeExtractionError
from job_agent.resume.extractor import extract_resume_text
from job_agent.resume.repository import list_versions
from job_agent.resume.service import create_profile_version

app = typer.Typer(help="Autonomous global job discovery and application agent.")
profile_app = typer.Typer(help="Candidate profile commands.")
jobs_app = typer.Typer(help="Job discovery commands (Phase 2+).")
applications_app = typer.Typer(help="Application pipeline commands (Phase 5+).")
allowlist_app = typer.Typer(
    help="Exact-posting submission allowlist (Phase 6C — controlled real-world execution)."
)
app.add_typer(profile_app, name="profile")
app.add_typer(jobs_app, name="jobs")
app.add_typer(applications_app, name="applications")
applications_app.add_typer(allowlist_app, name="allowlist")

console = Console()
logger = get_logger("job_agent.cli")


def _not_implemented(phase: str) -> None:
    console.print(
        f"[yellow]Not implemented yet.[/yellow] This command ships in {phase}. "
        "See README.md 'Roadmap' for the phased build plan."
    )
    raise typer.Exit(code=2)


@app.callback()
def main() -> None:
    configure_logging()


@app.command()
def init() -> None:
    """Scaffold missing config/candidate directories with safe defaults.

    Idempotent: never overwrites a file that already exists, so it's safe to
    run on a repo that already has real candidate data in it.
    """
    config_dir = REPO_ROOT / "config"
    candidate_dir = REPO_ROOT / "candidate"
    data_dir = REPO_ROOT / "data"
    data_dir.mkdir(exist_ok=True)

    missing = [p for p in (config_dir, candidate_dir) if not p.exists()]
    if missing:
        console.print(
            f"[red]Missing required directories:[/red] {[str(p) for p in missing]}. "
            "This scaffold ships with them committed; restore from git."
        )
        raise typer.Exit(code=1)

    env_example = REPO_ROOT / ".env.example"
    env_file = REPO_ROOT / ".env"
    if env_example.exists() and not env_file.exists():
        shutil.copy(env_example, env_file)
        console.print(f"Created [green]{env_file}[/green] from .env.example — fill in secrets.")
    else:
        console.print(".env already exists or no .env.example found — leaving as-is.")

    console.print("[green]init complete.[/green] config/ and candidate/ are ready.")


@profile_app.command("parse")
def profile_parse() -> None:
    """Parse candidate/*.md + config/*.yaml into the canonical CandidateProfile
    and persist it to the database."""
    start = time.monotonic()
    cfg = load_config()
    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        log_event(
            logger, component="cli.profile_parse", action="parse", result="failure", error=str(exc)
        )
        console.print(f"[red]Failed to parse candidate profile:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc

    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        candidate_id = save_candidate_profile(session, profile)

    duration_ms = (time.monotonic() - start) * 1000
    log_event(
        logger,
        component="cli.profile_parse",
        action="parse",
        result="success",
        duration_ms=duration_ms,
        candidate_id=candidate_id,
        skills=len(profile.skills),
        experience=len(profile.experience),
        projects=len(profile.projects),
    )

    table = Table(title="Candidate Profile Parsed")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Candidate ID", str(candidate_id))
    table.add_row("Name", profile.identity_name.value)
    table.add_row("Location", profile.identity_current_location.value)
    table.add_row("Experience entries", str(len(profile.experience)))
    table.add_row("Projects", str(len(profile.projects)))
    table.add_row("Skills", str(len(profile.skills)))
    table.add_row("Education", str(len(profile.education)))
    table.add_row("Certifications", str(len(profile.certifications)))
    visa_known = (
        "yes"
        if profile.visa_information.is_fully_known
        else "[yellow]NO — HUMAN_REVIEW_REQUIRED[/yellow]"
    )
    table.add_row("Visa info known", visa_known)
    console.print(table)

    with session_factory() as session:
        try:
            result = create_profile_version(session, cfg, profile, candidate_id)
        except ResumeExtractionError as exc:
            log_event(
                logger,
                component="cli.profile_parse",
                action="version",
                result="failure",
                error=str(exc),
            )
            console.print(
                f"[red]Could not read the authoritative resume file:[/red] {redact_text(str(exc))}"
            )
            raise typer.Exit(code=1) from exc

    if not result.passed:
        console.print(
            f"[red]Profile version {result.version.version_number} FAILED validation against "
            f"the resume — {len(result.issues)} unverifiable claim(s):[/red]"
        )
        for issue in result.issues:
            console.print(f"  [red]•[/red] [{issue.field}] {issue.detail}")
        log_event(
            logger,
            component="cli.profile_parse",
            action="version",
            result="failure",
            version_number=result.version.version_number,
            issue_count=len(result.issues),
        )
        raise typer.Exit(code=1)

    status_word = "created" if result.created else "unchanged"
    console.print(
        f"[green]Profile version {result.version.version_number}[/green] "
        f"({status_word}) — verified against resume_master.docx, 0 unverifiable claims."
    )
    log_event(
        logger,
        component="cli.profile_parse",
        action="version",
        result="success",
        version_number=result.version.version_number,
        created=result.created,
    )


@profile_app.command("history")
def profile_history() -> None:
    """List every candidate profile version, oldest first."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        console.print(f"[red]Failed to parse candidate profile:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc

    with session_factory() as session:
        candidate_id = save_candidate_profile(session, profile)
        versions = list_versions(session, candidate_id)

    if not versions:
        console.print(
            "[yellow]No profile versions yet.[/yellow] Run `job-agent profile parse` first."
        )
        raise typer.Exit(code=0)

    table = Table(title="Candidate Profile Version History")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Profile Hash")
    table.add_column("Resume Hash")
    table.add_column("Created At")
    for v in versions:
        status_str = (
            "[green]PASSED[/green]" if v.validation_status == "PASSED" else "[red]FAILED[/red]"
        )
        table.add_row(
            str(v.version_number),
            status_str,
            v.profile_hash[:12],
            v.resume_file_hash[:12],
            v.created_at.isoformat(),
        )
    console.print(table)


@app.command()
def status() -> None:
    """Show current configuration/safety-switch status."""
    cfg = load_config()
    table = Table(title="job-agent status")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("dry_run", "[green]true[/green]" if cfg.dry_run else "[red]false[/red]")
    table.add_row("live_mode", "[red]true[/red]" if cfg.live_mode else "[green]false[/green]")
    table.add_row(
        "submission_allowed",
        "[red]YES[/red]" if cfg.is_submission_allowed() else "[green]no[/green]",
    )
    table.add_row("automation_level", str(cfg.automation.automation.level))
    table.add_row("database_url", cfg.env.database_url)
    console.print(table)


@app.command()
def health() -> None:
    """Basic health check: config loads, candidate files parse, DB reachable."""
    checks: list[tuple[str, bool, str]] = []

    try:
        cfg = load_config()
        checks.append(("config", True, "loaded"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("config", False, redact_text(str(exc))))
        cfg = None

    if cfg is not None:
        try:
            parse_candidate_profile(cfg)
            checks.append(("candidate_profile", True, "parses cleanly"))
        except Exception as exc:  # noqa: BLE001
            checks.append(("candidate_profile", False, redact_text(str(exc))))

        try:
            engine = get_engine(cfg.env.database_url)
            init_db(engine)
            # database_url may embed a credential for a non-SQLite
            # deployment (scheme://user:password@host/db) — must never be
            # displayed unredacted, success path included.
            checks.append(("database", True, redact_text(cfg.env.database_url)))
        except Exception as exc:  # noqa: BLE001
            checks.append(("database", False, redact_text(str(exc))))

    table = Table(title="job-agent health")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    all_ok = True
    for name, ok, detail in checks:
        all_ok &= ok
        table.add_row(name, "[green]OK[/green]" if ok else "[red]FAIL[/red]", detail)
    console.print(table)
    if not all_ok:
        raise typer.Exit(code=1)


@app.command(name="dry-run")
def dry_run() -> None:
    """Confirm the system is in dry-run mode (no submissions possible)."""
    cfg = load_config()
    if cfg.is_submission_allowed():
        console.print(
            "[red]WARNING: submission IS currently allowed "
            "(DRY_RUN=false, LIVE_MODE=true).[/red]"
        )
        raise typer.Exit(code=1)
    console.print(
        "[green]Safe:[/green] dry-run mode active — no application will ever be submitted."
    )


@jobs_app.command("scan")
def jobs_scan() -> None:
    """Poll all enabled job sources and persist newly discovered/updated jobs."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        results = run_scan(session, cfg)

    if not results:
        console.print(
            "[yellow]No job sources are enabled.[/yellow] Edit config/sources.yaml "
            "(set enabled: true and fill in real board tokens) to scan for jobs."
        )
        raise typer.Exit(code=0)

    table = Table(title="Job Scan Results")
    table.add_column("Source")
    table.add_column("Board")
    table.add_column("Fetched")
    table.add_column("Created")
    table.add_column("Updated")
    table.add_column("Errors")
    total_errors = 0
    for r in results:
        total_errors += len(r.errors)
        table.add_row(
            r.source_name,
            r.identifier,
            str(r.fetched),
            str(r.created),
            str(r.updated),
            str(len(r.errors)) if not r.errors else f"[red]{len(r.errors)}[/red]",
        )
    console.print(table)
    for r in results:
        for err in r.errors:
            console.print(f"[red]{r.source_name}/{r.identifier}:[/red] {err}")

    log_event(
        logger,
        component="cli.jobs_scan",
        action="scan",
        result="success" if not total_errors else "partial_failure",
        sources_scanned=len(results),
        total_errors=total_errors,
    )
    if total_errors:
        raise typer.Exit(code=1)


@jobs_app.command("match")
def jobs_match() -> None:
    """Score every job in the database against the candidate profile."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        console.print(f"[red]Failed to parse candidate profile:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc

    llm = build_llm_provider(cfg)
    llm_note = (
        "[green]enabled[/green]"
        if not isinstance(llm, NullLLMProvider)
        else "[yellow]disabled — no ANTHROPIC_API_KEY[/yellow]"
    )
    console.print(f"Semantic matching: {llm_note}")

    with session_factory() as session:
        candidate_id = save_candidate_profile(session, profile)
        try:
            outcomes = run_matching(session, cfg, profile, candidate_id, llm=llm)
        except ValueError as exc:
            console.print(f"[red]{redact_text(str(exc))}[/red]")
            raise typer.Exit(code=1) from exc

    if not outcomes:
        console.print(
            "[yellow]No jobs in the database yet.[/yellow] Run `job-agent jobs scan` first."
        )
        raise typer.Exit(code=0)

    table = Table(title="Match Results")
    table.add_column("Job ID")
    table.add_column("Company")
    table.add_column("Title")
    table.add_column("Score")
    table.add_column("Decision")
    table.add_column("Semantic")
    decision_colors = {
        "APPLY": "green",
        "REVIEW": "cyan",
        "SAVE": "blue",
        "SKIP": "dim",
        "HUMAN_REQUIRED": "red",
    }
    for outcome in outcomes:
        color = decision_colors.get(outcome.result.decision.value, "white")
        table.add_row(
            str(outcome.job_id),
            outcome.company,
            outcome.title,
            str(outcome.result.overall_score),
            f"[{color}]{outcome.result.decision.value}[/{color}]",
            "yes" if outcome.semantic_call_made else "no",
        )
    console.print(table)

    log_event(
        logger,
        component="cli.jobs_match",
        action="match",
        result="success",
        jobs_matched=len(outcomes),
        semantic_calls=sum(1 for o in outcomes if o.semantic_call_made),
    )


@applications_app.command("prepare")
def applications_prepare() -> None:
    """Discover + prepare an Application for every job_matches row that
    doesn't have one yet (APPLY/REVIEW decisions proceed toward PREPARED;
    HUMAN_REQUIRED/SAVE/SKIP land in the matching states directly).

    Each job is processed independently (`prepare_applications_batch`) —
    one job raising an unexpected error is logged and skipped, it never
    aborts preparation for the rest of the batch (Phase 6A)."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        console.print(f"[red]Failed to parse candidate profile:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc

    llm = build_llm_provider(cfg)

    with session_factory() as session:
        candidate_id = save_candidate_profile(session, profile)
        job_matches = list(
            session.execute(
                select(JobMatch).where(JobMatch.candidate_id == candidate_id)
            ).scalars()
        )
        # Only the most recent match per job matters for deciding what to prepare.
        latest_by_job: dict[int, JobMatch] = {}
        for jm in job_matches:
            latest_by_job[jm.job_id] = jm

        items = []
        for job_id, jm in latest_by_job.items():
            job = session.get(JobRow, job_id)
            if job is None:
                continue
            items.append((job, jm))

        # Phase 6B: which ApplicationProvider to use is config-driven
        # (`config.automation.application_provider`), mirroring
        # `job_agent.jobs.service.build_sources`'s pattern. Default
        # ("manual_review") is byte-for-byte the same provider this
        # command has always hardcoded — StructuredATSProvider only ever
        # runs when explicitly enabled, and only against a local fixture
        # file (never a network call, never a real ATS). A misconfigured
        # fixture_path (e.g. a typo) must fail loudly with a clear,
        # redacted message here — never as an unhandled traceback, and
        # never by silently falling back to a different provider.
        try:
            provider = build_application_provider(cfg, [job for job, _ in items])
        except (FileNotFoundError, ValueError) as exc:
            console.print(
                f"[red]Failed to resolve application provider:[/red] {redact_text(str(exc))}"
            )
            raise typer.Exit(code=1) from exc
        if provider.name != "manual_review":
            console.print(
                f"[cyan]Using application provider:[/cyan] {provider.name} "
                "(local fixture data only — submission remains disabled)"
            )

        outcomes = prepare_applications_batch(
            session, cfg, items, candidate_id, profile, provider, llm=llm
        )

        # Phase 6B: surface *why* an application landed at HUMAN_REQUIRED
        # (CAPTCHA/MFA/consent/unexpected form, an inspection-stage
        # provider error, or a hard-block/missing-fact answer) — read
        # while `session` is still open, since the audit trail lives in
        # the DB, not on the in-memory outcome. `get_latest_event` is
        # read-only and returns already-redacted `details` (every
        # `ApplicationEvent` row is redacted at write time by
        # `record_event`), so nothing here needs its own redaction pass.
        # This is purely informational — it changes nothing about which
        # provider ran, whether inspection happened (still governed
        # entirely by `provider.supports_inspection`), or how the status
        # was decided; only production, not real submission, behavior.
        reasons: dict[int, str] = {}
        for item in outcomes:
            if item.application is not None and item.application.status == (
                ApplicationStatus.HUMAN_REQUIRED.value
            ):
                event = get_latest_event(session, item.application.id)
                if event is not None:
                    reasons[item.application.id] = event.event_type

    if not outcomes:
        console.print(
            "[yellow]No job matches found.[/yellow] Run `job-agent jobs match` first."
        )
        raise typer.Exit(code=0)

    table = Table(title="Application Preparation")
    table.add_column("Job ID")
    table.add_column("Company")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Detail")
    status_colors = {
        "PREPARED": "green", "HUMAN_REQUIRED": "yellow", "SKIPPED": "dim",
        "FAILED": "red", "MATCHED": "cyan",
    }
    error_count = 0
    for item in outcomes:
        if item.error is not None or item.application is None:
            error_count += 1
            table.add_row(
                str(item.job.id), item.job.company_name, item.job.title,
                "[red]ERROR[/red]", item.error or "unknown error",
            )
            continue
        color = status_colors.get(item.application.status, "white")
        detail = ""
        if item.application.status == ApplicationStatus.HUMAN_REQUIRED.value:
            detail = reasons.get(item.application.id, "")
        table.add_row(
            str(item.job.id), item.job.company_name, item.job.title,
            f"[{color}]{item.application.status}[/{color}]", detail,
        )
    console.print(table)
    if error_count:
        console.print(
            f"[red]{error_count} job(s) failed to process[/red] — see the Detail column "
            "and logs; every other job in this run was processed independently."
        )


@applications_app.command("review")
def applications_review() -> None:
    """List every application currently awaiting human input."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        pending = list(
            session.execute(
                select(Application).where(
                    Application.status == ApplicationStatus.HUMAN_REQUIRED.value
                )
            ).scalars()
        )
        if not pending:
            console.print("[green]Nothing awaiting human review.[/green]")
            raise typer.Exit(code=0)

        for application in pending:
            job = session.get(JobRow, application.job_id)
            console.print(
                f"\n[bold]{job.company_name if job else '?'} — "
                f"{job.title if job else '?'}[/bold] (application id {application.id})"
            )
            answers = get_answers(session, application.id)
            for answer in answers:
                if not answer.requires_human:
                    continue
                console.print(f"  [yellow]?[/yellow] {answer.question_text}")
                for note in answer.validation_notes or []:
                    console.print(f"      {note}")


@applications_app.command("target-add")
def applications_target_add(
    url: str = typer.Option(
        ..., "--url", help="Exact application-form URL for this one target. Stored exactly "
        "as given -- never crawled, never fetched, no network call is made.",
    ),
    company: str = typer.Option(..., "--company", help="Company name (display only)."),
    title: str = typer.Option(..., "--title", help="Job title (display only)."),
    location: str = typer.Option(
        "", "--location", help="Optional location (display only)."
    ),
) -> None:
    """Register exactly ONE explicit job target for local preparation --
    the minimum Job + Application metadata `applications browser-preview`
    needs, so a real target URL can be used without hand-constructing
    database rows. Makes NO network call and discovers NO other jobs:
    reuses the existing job-persistence path (`jobs.repository.
    upsert_job`) under a dedicated, disabled "manual" JobSource, so this
    can never be picked up by `jobs scan` -- that command builds its
    adapters entirely from config.sources, never from JobSource DB rows.

    Writes ONLY local metadata: no inspection, no form filling, no resume
    upload, no approval, no allowlist entry, and no submission of any
    kind. Run `applications browser-preview <application id> --url
    <url> --confirm` next to actually inspect and prepare against it.
    """
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        console.print(f"[red]Failed to parse candidate profile:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc

    # source_job_id=url (not an auto-incrementing counter or a random
    # id): this is the SAME (source_id, source_job_id) identity key
    # upsert_job already uses for dedup, so registering the identical
    # --url twice updates the existing row rather than creating a
    # duplicate, with no new logic required here.
    manual_job = JobTargetSchema(
        source="manual",
        source_job_id=url,
        company=company,
        title=title,
        location=location or None,
        application_url=url,
    )

    with session_factory() as session:
        candidate_id = save_candidate_profile(session, profile)
        source_row = get_or_create_job_source(
            session, name="manual", kind="manual", enabled=False
        )
        job_row, job_created = upsert_job(
            session, manual_job, source_row=source_row,
            freshness_status=FreshnessStatus.UNKNOWN_POST_DATE,
        )
        application, app_created = get_or_create_application(
            session, job_row.id, candidate_id, dry_run=cfg.dry_run,
        )
        session.commit()
        job_id = job_row.id
        application_id = application.id

    console.print(
        f"[green]Target registered.[/green] job id {job_id} "
        f"({'new' if job_created else 'existing, updated'}), application id {application_id} "
        f"({'new' if app_created else 'existing'}).\n"
        f"  Company: {company}\n  Title: {title}\n  URL: {url}\n\n"
        "Next:\n"
        f'  job-agent applications browser-preview {application_id} --url "{url}" --confirm'
    )


def _parse_answer_overrides(answer: list[str] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for entry in answer or []:
        if "=" not in entry:
            console.print(
                f'[red]--answer must be "<question text>=<value>", got:[/red] {entry!r}'
            )
            raise typer.Exit(code=1)
        question_label, _, value = entry.partition("=")
        overrides[question_label] = value
    return overrides


@dataclass(frozen=True)
class _BrowserPrepareResult:
    job: JobRow
    snapshot: HumanReviewSnapshot
    unresolved_questions: tuple[str, ...]


def _run_browser_preparation(
    cfg: AppConfig,
    session: Session,
    application: Application,
    url: str,
    human_input_overrides: dict[str, str],
) -> _BrowserPrepareResult:
    """The ONE shared discover -> inspect -> evaluate_inspection ->
    get_questions -> generate_answer -> apply_human_input_overrides ->
    fill_application -> get_snapshot pipeline every `applications
    browser-*` command uses — so "prepare" means exactly the same thing
    everywhere it's invoked, never a second, slightly-different
    implementation. Opens exactly ONE fresh browser session, navigates to
    `url` exactly once, and always closes the browser before returning
    (or raising). A CAPTCHA/MFA/consent/unrecognized-structure verdict or
    any other stop condition raises `typer.Exit` directly (code 0 for
    "human review needed, nothing is wrong", code 1 for a real failure)
    rather than returning a sentinel, matching the exact codes this
    pipeline has always used.

    NEVER passes `resume_path` to `BrowserApplicationProvider` — a resume
    is never automatically attached by any caller of this helper; see
    each command's own docstring for why.
    """
    job = session.get(JobRow, application.job_id)
    if job is None:
        console.print(f"[red]Application {application.id} has no matching job row.[/red]")
        raise typer.Exit(code=1)
    if url != job.application_url:
        console.print(
            "[red]--url does not match this job's own application_url.[/red]\n"
            f"  --url:                {url}\n"
            f"  job.application_url:  {job.application_url}\n"
            "Pass the exact URL the job itself already carries — never a different one."
        )
        raise typer.Exit(code=1)

    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        console.print(f"[red]Failed to parse candidate profile:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc

    resume_path = cfg.env.candidate_dir / "resume_master.docx"
    try:
        resume_text = extract_resume_text(resume_path)
    except ResumeExtractionError as exc:
        console.print(f"[red]Failed to extract resume text:[/red] {redact_text(str(exc))}")
        raise typer.Exit(code=1) from exc
    answer_bank = load_answer_bank(cfg.env.candidate_dir / "answers")
    llm = build_llm_provider(cfg)

    from playwright.sync_api import sync_playwright

    snapshot = None
    answers: list[GeneratedAnswer] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # Real-target-readiness checkpoint: resume_path is
            # DELIBERATELY never passed here. Passing it would make
            # BrowserApplicationProvider.fill_application() attach the
            # resume automatically the instant a file field is visible --
            # with no check for whether that field is even required.
            # `resume_text` above is still extracted and used for LLM
            # answer validation (checking a claim against the resume's
            # actual content), which is unrelated to file upload.
            # Attaching a resume is a separate, explicit action a human
            # takes later, not an automatic side effect of this pipeline.
            provider = BrowserApplicationProvider({job.id: url}, browser=browser)
            target = provider.discover_application(job)
            if not target.reachable:
                console.print(f"[red]Could not reach target:[/red] {target.detail}")
                raise typer.Exit(code=1)

            inspection = provider.inspect_application(job, target)
            verdict = evaluate_inspection(cfg.rules, inspection)
            if verdict.human_required:
                console.print(
                    f"[yellow]Human review required before filling:[/yellow] "
                    f"{verdict.reason} — nothing was filled."
                )
                raise typer.Exit(code=0)

            questions = provider.get_questions(job)
            answers = [
                generate_answer(q, profile, resume_text, answer_bank, llm)
                for q in questions
            ]
            answers = apply_human_input_overrides(answers, human_input_overrides)
            applied_labels = {
                a.question for a in answers if a.source.startswith(HUMAN_INPUT_SOURCE_PREFIX)
            }
            for label in set(human_input_overrides) - applied_labels:
                console.print(
                    f"[yellow]--answer {label!r} was not applied[/yellow] — either no "
                    "question on this form has that exact text, or it was already "
                    "resolved (a trusted fact/answer-bank/LLM answer is never overridden)."
                )
            provider.fill_application(job, target, answers)
            snapshot = provider.get_snapshot(job.id)
        except ProviderError as exc:
            console.print(f"[red]Provider error:[/red] {redact_text(str(exc))}")
            raise typer.Exit(code=1) from exc
        finally:
            browser.close()

    if snapshot is None:
        console.print("[red]No snapshot was produced.[/red]")
        raise typer.Exit(code=1)
    unresolved_questions = tuple(a.question for a in answers if a.requires_human)
    return _BrowserPrepareResult(
        job=job, snapshot=snapshot, unresolved_questions=unresolved_questions
    )


@applications_app.command("browser-preview")
def applications_browser_preview(
    application_id: int = typer.Argument(..., help="Application id to preview."),
    url: str = typer.Option(
        ...,
        "--url",
        help="Exact application-form URL to load — must match this application's job's "
        "own application_url exactly, so nothing is ever contacted based on unstated "
        "database content alone.",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Actually launch a browser and contact --url; without this, reports what "
        "would happen and makes no network call.",
    ),
    # The standard typer repeatable-option pattern; ruff's built-in typer
    # exemption for B008 doesn't cover a list[...]-typed default.
    answer: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--answer",
        help='Human-supplied answer for a question that is CURRENTLY unresolved, as '
        '"<question text>=<value>" (e.g. "Current company=Instawork"). May be repeated. '
        "Applied only to a question the answer engine already left requires_human=True — "
        "a question already resolved from a trusted fact, the answer bank, or the LLM is "
        "never overridden. Never written to CandidateProfile, never sent to the LLM (this "
        "runs after every answer has already been generated), and shown in the review "
        'output with "Source: Human input", always distinguishable from a trusted fact.',
    ),
) -> None:
    """Build and render a HumanReviewSnapshot for ONE application (Phase 6D
    Stage 2) — discovers the real form via BrowserApplicationProvider,
    generates truthful answers through the existing, unmodified
    answer_engine pipeline, fills them into the live DOM, and shows a
    human exactly what was filled, what still needs their input, and any
    safety condition. Never transmits or submits anything —
    BrowserApplicationProvider.submit() remains structurally incapable of
    that regardless.

    CAPTCHA/MFA/consent-required facts are routed through the same,
    unmodified rules_enforcement.evaluate_inspection() every other
    inspecting provider uses; a HUMAN_REQUIRED verdict stops this command
    before a single field is filled. This is a read-only preview — it
    writes nothing to the database and does not compete with
    `applications prepare` for ownership of an application's status, and
    it creates no approval: pure preview, nothing is remembered.
    """
    human_input_overrides = _parse_answer_overrides(answer)
    if not confirm:
        console.print(
            "[yellow]No action taken.[/yellow] Pass --confirm to actually contact "
            f"{url} and build a preview for application {application_id}."
        )
        raise typer.Exit(code=0)

    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            console.print(f"[red]No application with id {application_id}.[/red]")
            raise typer.Exit(code=1)
        result = _run_browser_preparation(cfg, session, application, url, human_input_overrides)

    render_snapshot(result.snapshot, console)


@applications_app.command("browser-approve")
def applications_browser_approve(
    application_id: int = typer.Argument(..., help="Application id to approve."),
    url: str = typer.Option(
        ..., "--url", help="Exact application-form URL — must match this application's "
        "job's own application_url exactly.",
    ),
    answer: list[str] | None = typer.Option(  # noqa: B008
        None, "--answer",
        help='Human-supplied answer for a currently-unresolved question, as '
        '"<question text>=<value>". May be repeated. Same semantics as '
        "`browser-preview --answer` — see that command's help.",
    ),
    ttl_hours: int = typer.Option(
        24, "--ttl-hours", help="Hours this approval stays valid before expiring unused."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the interactive confirmation prompt."
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="Actually launch a browser and contact --url; without this, reports what "
        "would happen and makes no network call.",
    ),
) -> None:
    """Record a human's approval to browser-fill ONE specific application,
    bound to its EXACT current job content (`job.job_fingerprint`) and
    EXACT current, DOM-verified prepared state
    (`compute_snapshot_fingerprint` — field structure, proposed values,
    uploaded files, and what's still unresolved). Reuses the existing
    Phase 6C `ApplicationApproval` model and `job_agent.applications.
    approvals` module completely unchanged — this is the SAME single-use,
    fingerprint-bound approval `applications approve` already creates for
    the structured-ATS submission pipeline, just bound to a browser
    session's snapshot fingerprint instead of `answers_from_db()`'s.
    `applications browser-fill` is the only command that ever consumes
    this approval, and only if a FRESH re-inspection still matches it
    exactly.

    Every question must already be resolved (via a trusted fact, the
    answer bank, the LLM, or --answer) before this command will approve
    anything — exactly like `applications approve` requires for the
    structured pipeline. Nothing is submitted; `submit()` is not called
    by this command or by anything it triggers.
    """
    human_input_overrides = _parse_answer_overrides(answer)
    if not confirm:
        console.print(
            "[yellow]No action taken.[/yellow] Pass --confirm to actually contact "
            f"{url} and review application {application_id} for approval."
        )
        raise typer.Exit(code=0)

    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            console.print(f"[red]No application with id {application_id}.[/red]")
            raise typer.Exit(code=1)
        result = _run_browser_preparation(cfg, session, application, url, human_input_overrides)

        if result.unresolved_questions:
            console.print(
                f"[red]Application {application_id} still has question(s) requiring human "
                "input:[/red]"
            )
            for question in result.unresolved_questions:
                console.print(f"    ? {question}")
            console.print(
                'Resolve them with --answer "<question text>=<value>" before approving.'
            )
            raise typer.Exit(code=1)

        render_snapshot(result.snapshot, console)
        posting_fingerprint = result.job.job_fingerprint
        answer_fingerprint = compute_snapshot_fingerprint(result.snapshot)
        console.print(f"\n  Job fingerprint:      {posting_fingerprint}")
        console.print(f"  Snapshot fingerprint: {answer_fingerprint}")

        if not yes:
            typer.confirm(
                "\nApprove this EXACT prepared application for one real browser fill?",
                abort=True,
            )

        approval = create_approval(
            session, application.id, posting_fingerprint, answer_fingerprint,
            ttl_hours=ttl_hours,
        )
        session.commit()

    console.print(
        f"[green]Approved.[/green] approval id {approval.id}, expires at "
        f"{approval.expires_at.isoformat()} — single-use, bound to this exact prepared state.\n"
        "Next:\n"
        f'  job-agent applications browser-fill {application_id} --url "{url}" --confirm'
        + "".join(f' --answer "{k}={v}"' for k, v in human_input_overrides.items())
    )


@applications_app.command("browser-fill")
def applications_browser_fill(
    application_id: int = typer.Argument(..., help="Application id to fill."),
    url: str = typer.Option(
        ..., "--url", help="Exact application-form URL — must match this application's "
        "job's own application_url exactly.",
    ),
    answer: list[str] | None = typer.Option(  # noqa: B008
        None, "--answer",
        help="The SAME --answer value(s) used at `browser-approve` time — must reproduce "
        "the identical prepared state, or the freshly-computed snapshot fingerprint won't "
        "match the approval and this command will refuse to proceed.",
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="Actually launch a browser and fill the approved fields; without this, "
        "reports what would happen and makes no network call.",
    ),
) -> None:
    """Fills the browser DOM with the approved values for ONE application
    — the ONLY command in this codebase that fills a form on the strength
    of a prior human approval, and it never proceeds without one.

    Re-runs the FULL preparation pipeline in a FRESH browser session (a
    new navigation, a fresh DOM read) — never reuses a cached result from
    `browser-approve`. If the freshly re-inspected form now shows a
    CAPTCHA/MFA/password field/unrecognized structure, this stops exactly
    like `browser-preview` does, before typing anything. The values are
    then filled into this throwaway, soon-to-be-closed browser session
    (harmless on its own — nothing is transmitted to the target),  and
    ONLY THEN is the resulting snapshot's fingerprint checked against
    `applications browser-approve`'s stored approval — bound to this
    exact application, this exact job content, and this exact prepared
    state. Any drift (a different answer, a changed job posting, an
    expired/already-consumed/revoked approval, or simply no approval at
    all) is treated identically: refuse, explain why, and require a new
    `browser-approve` — never silently re-approve and continue. A valid
    approval is consumed (single-use) the moment it is accepted, so it
    can never be replayed for a second fill.

    Stops immediately after filling and recording the audit event.
    `submit()` is never called by this command or anything it triggers —
    BrowserApplicationProvider.submit() remains structurally incapable of
    submitting regardless.
    """
    human_input_overrides = _parse_answer_overrides(answer)
    if not confirm:
        console.print(
            "[yellow]No action taken.[/yellow] Pass --confirm to actually contact "
            f"{url} and fill application {application_id} (requires a valid approval)."
        )
        raise typer.Exit(code=0)

    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            console.print(f"[red]No application with id {application_id}.[/red]")
            raise typer.Exit(code=1)
        result = _run_browser_preparation(cfg, session, application, url, human_input_overrides)

        posting_fingerprint = result.job.job_fingerprint
        answer_fingerprint = compute_snapshot_fingerprint(result.snapshot)
        approval = get_valid_approval(
            session, application.id, posting_fingerprint, answer_fingerprint
        )
        if approval is None:
            console.print(
                "[red]No valid approval matches the current prepared state.[/red]\n"
                "This means at least one of: no approval exists yet, it expired, it was "
                "already consumed by an earlier fill, it was revoked, or the form/answers "
                "changed since you last ran `applications browser-approve` (a different "
                "job posting, different --answer values, or a newly-appeared form field). "
                "Nothing was filled as approved. Run `applications browser-approve` again "
                "to review and approve the CURRENT state, then re-run this command."
            )
            raise typer.Exit(code=1)

        consume_approval(session, approval)
        record_event(
            session, application.id, "BROWSER_FILL_COMPLETED",
            {"approval_id": approval.id, "job_id": result.job.id},
        )
        session.commit()

    render_snapshot(result.snapshot, console)
    console.print(
        "\n[bold yellow]STOPPED BEFORE SUBMISSION.[/bold yellow] Nothing above was ever "
        "transmitted anywhere. Automated submission is structurally unavailable — "
        "BrowserApplicationProvider.submit() always refuses. Review the fields above "
        "manually on the real site before doing anything further."
    )


@applications_app.command("run")
def applications_run() -> None:
    """Attempt submission for every PREPARED application.

    There is no real ATS integration in this phase — `ManualReviewProvider`
    always refuses (see job_agent.applications.provider) — so this command
    exists to exercise the safety gates honestly and report exactly what a
    human still needs to do, never to actually submit anything.

    Each application is processed independently
    (`submit_applications_batch`) — one raising an unexpected error is
    logged and skipped, it never aborts submission attempts for the rest
    of the batch (Phase 6A)."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)
    provider = ManualReviewProvider()

    if not cfg.is_submission_allowed():
        console.print(
            "[green]Safe:[/green] dry-run mode active — no submission will be attempted; "
            "this command will only report what would happen."
        )

    with session_factory() as session:
        prepared = list(
            session.execute(
                select(Application).where(Application.status == ApplicationStatus.PREPARED.value)
            ).scalars()
        )
        if not prepared:
            console.print("[yellow]No PREPARED applications to submit.[/yellow]")
            raise typer.Exit(code=0)

        items = []
        for application in prepared:
            job = session.get(JobRow, application.job_id)
            if job is None:
                continue
            items.append((application, job))

        outcomes = submit_applications_batch(session, cfg, items, provider)

    error_count = 0
    for item in outcomes:
        if item.error is not None or item.application is None:
            error_count += 1
            console.print(
                f"{item.job.company_name} — {item.job.title}: [red]ERROR[/red] ({item.error})"
            )
            continue
        console.print(
            f"{item.job.company_name} — {item.job.title}: [cyan]{item.application.status}[/cyan]"
            + (f" ({item.application.error_message})" if item.application.error_message else "")
        )
    if error_count:
        console.print(
            f"[red]{error_count} application(s) failed to process[/red] — see the messages "
            "above and logs; every other application in this run was attempted independently."
        )


@applications_app.command("approve")
def applications_approve(
    application_id: int = typer.Argument(..., help="Application id to approve."),
    ttl_hours: int = typer.Option(
        24, "--ttl-hours", help="Hours this approval stays valid before expiring unused."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the interactive confirmation prompt."
    ),
) -> None:
    """Record a human's approval to submit ONE specific application, bound
    to its EXACT current job content and EXACT current answers (Phase 6C
    — controlled real-world execution).

    This is the only way to satisfy the approval half of
    `submit_application`'s gate for a provider with
    `requires_persisted_approval = True` (e.g. `real_structured_ats`) —
    no automation level and no other flag can substitute for it; that
    provider never even looks at automation level. The approval is
    single-use and expires after `--ttl-hours` (default 24); re-running
    `applications prepare` regenerates answers and invalidates any
    outstanding approval, since its answer fingerprint would no longer
    match. Approving also requires a matching, unexpired allowlist entry
    (see `applications allowlist add`) — this command only ever creates
    the approval half of the gate, never the allowlist half.
    """
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            console.print(f"[red]No application with id {application_id}.[/red]")
            raise typer.Exit(code=1)
        if application.status != ApplicationStatus.PREPARED.value:
            console.print(
                f"[red]Application {application_id} is {application.status}, not "
                "PREPARED.[/red] Only a PREPARED application can be approved."
            )
            raise typer.Exit(code=1)
        job = session.get(JobRow, application.job_id)
        if job is None:
            console.print(f"[red]Application {application_id} has no matching job row.[/red]")
            raise typer.Exit(code=1)

        answers = answers_from_db(session, application.id)
        if any(a.requires_human for a in answers):
            console.print(
                f"[red]Application {application_id} still has answer(s) requiring human "
                "input.[/red] Resolve them via `applications review` before approving."
            )
            raise typer.Exit(code=1)

        console.print(
            f"\n[bold]{job.company_name} — {job.title}[/bold] "
            f"(application id {application.id})"
        )
        console.print(f"  Target URL: {job.application_url}")
        console.print(f"  Job fingerprint: {job.job_fingerprint}")
        console.print(f"  {len(answers)} answer(s) will be submitted if approved:")
        for answer in answers:
            console.print(f"    Q: {answer.question}")
            console.print(f"    A: {answer.answer}")

        if not yes:
            typer.confirm(
                "\nApprove this EXACT application (this job content + these exact "
                "answers) for one real submission attempt?",
                abort=True,
            )

        answer_fingerprint = compute_answer_fingerprint(answers)
        approval = create_approval(
            session, application.id, job.job_fingerprint, answer_fingerprint,
            ttl_hours=ttl_hours,
        )
        session.commit()

    console.print(
        f"[green]Approved.[/green] approval id {approval.id}, expires at "
        f"{approval.expires_at.isoformat()} — single-use, bound to this exact content."
    )


@applications_app.command("submit")
def applications_submit(
    application_id: int = typer.Argument(..., help="Application id to submit."),
    confirm: bool = typer.Option(
        False, "--confirm", help="Actually attempt the submission; without this, no-op."
    ),
) -> None:
    """Attempt a real submission for ONE application (Phase 6C).

    Unlike `applications run` (which always uses `ManualReviewProvider`
    and can never actually submit anything), this command resolves the
    provider from config exactly like `applications prepare` does
    (`build_application_provider`) — so it CAN reach a real provider if
    one is explicitly configured. Every safety gate in
    `job_agent.applications.service.submit_application` still applies in
    full: dry_run/live_mode, rate limits, and — for a provider with
    `requires_persisted_approval = True` — a valid allowlist entry AND a
    valid `applications approve`-created approval bound to this exact
    content. Without `--confirm`, this command does nothing and makes no
    database change.
    """
    if not confirm:
        console.print(
            "[yellow]No action taken.[/yellow] Pass --confirm to actually attempt "
            f"submission for application {application_id}."
        )
        raise typer.Exit(code=0)

    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            console.print(f"[red]No application with id {application_id}.[/red]")
            raise typer.Exit(code=1)
        job = session.get(JobRow, application.job_id)
        if job is None:
            console.print(f"[red]Application {application_id} has no matching job row.[/red]")
            raise typer.Exit(code=1)

        provider = build_application_provider(cfg, [job])
        try:
            result = submit_application(session, cfg, application, job, provider)
        except IllegalStateTransitionError as exc:
            console.print(
                f"[red]Cannot submit application {application_id}:[/red] {exc}. Only a "
                "PREPARED application can be submitted."
            )
            raise typer.Exit(code=1) from exc

    console.print(
        f"Application {application_id} ({job.company_name} — {job.title}): "
        f"[cyan]{result.status}[/cyan]"
        + (f" ({result.error_message})" if result.error_message else "")
    )


@applications_app.command("verify")
def applications_verify(
    application_id: int = typer.Argument(..., help="Application id to verify."),
) -> None:
    """Attempt to independently verify a prior SUBMITTED application
    (Phase 6C). Only `verify_application` can reach VERIFIED; for a
    provider with `requires_persisted_approval = True`, this additionally
    requires `job_agent.applications.verification_contract.validate_
    submission_evidence` to pass, on top of the provider's own
    `verified=True` + concrete-evidence result."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            console.print(f"[red]No application with id {application_id}.[/red]")
            raise typer.Exit(code=1)
        job = session.get(JobRow, application.job_id)
        if job is None:
            console.print(f"[red]Application {application_id} has no matching job row.[/red]")
            raise typer.Exit(code=1)

        provider = build_application_provider(cfg, [job])
        try:
            result = verify_application(session, application, job, provider)
        except IllegalStateTransitionError as exc:
            console.print(
                f"[red]Cannot verify application {application_id}:[/red] {exc}. Only a "
                "SUBMITTED application can be verified."
            )
            raise typer.Exit(code=1) from exc

    console.print(
        f"Application {application_id} ({job.company_name} — {job.title}): "
        f"[cyan]{result.status}[/cyan]"
    )


@allowlist_app.command("add")
def allowlist_add(
    job_id: int = typer.Argument(..., help="Job id to allowlist for real submission."),
    provider_name: str = typer.Argument(
        ..., help='Exact provider name, e.g. "real_structured_ats".'
    ),
    ttl_days: int = typer.Option(
        7, "--ttl-days", help="Days this allowlist entry stays valid before expiring unused."
    ),
) -> None:
    """Allowlist exactly ONE posting for exactly ONE provider (Phase 6C).

    Keyed by the job's current content fingerprint and its CURRENT
    `application_url` — never a company, a search query, or a domain.
    `submit_application` requires the job's `application_url` to still
    match this exact URL at submission time; a drifted target blocks
    rather than silently following the new URL. This is only half of
    the submission gate — an `applications approve`-created approval is
    still required separately for each individual application.
    """
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        job = session.get(JobRow, job_id)
        if job is None:
            console.print(f"[red]No job with id {job_id}.[/red]")
            raise typer.Exit(code=1)
        if not job.application_url:
            console.print(f"[red]Job {job_id} has no application_url to allowlist.[/red]")
            raise typer.Exit(code=1)

        entry = create_allowlist_entry(
            session, job.job_fingerprint, provider_name, job.application_url, ttl_days=ttl_days,
        )
        session.commit()

    console.print(
        f"[green]Allowlisted.[/green] entry id {entry.id}, provider {provider_name!r}, "
        f"url {entry.canonical_url!r}, expires at {entry.expires_at.isoformat()}."
    )


@allowlist_app.command("revoke")
def allowlist_revoke(
    entry_id: int = typer.Argument(..., help="Allowlist entry id to revoke."),
) -> None:
    """Revoke one allowlist entry immediately — any application whose
    submission attempt would have relied on it is blocked from that
    point on, even if the entry hadn't expired yet."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        entry = session.get(ApplicationAllowlistEntry, entry_id)
        if entry is None:
            console.print(f"[red]No allowlist entry with id {entry_id}.[/red]")
            raise typer.Exit(code=1)
        revoke_allowlist_entry(session, entry)
        session.commit()

    console.print(f"[green]Revoked.[/green] allowlist entry id {entry_id}.")


@allowlist_app.command("list")
def allowlist_list() -> None:
    """List every allowlist entry (active, expired, and revoked) — purely
    informational, read-only."""
    cfg = load_config()
    engine = get_engine(cfg.env.database_url)
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        entries = list(
            session.execute(
                select(ApplicationAllowlistEntry).order_by(ApplicationAllowlistEntry.id.desc())
            ).scalars()
        )

    if not entries:
        console.print("[yellow]No allowlist entries.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="Submission Allowlist")
    table.add_column("ID")
    table.add_column("Provider")
    table.add_column("URL")
    table.add_column("Expires At")
    table.add_column("Revoked")
    for entry in entries:
        table.add_row(
            str(entry.id), entry.provider_name, entry.canonical_url,
            entry.expires_at.isoformat(), "yes" if entry.revoked_at else "no",
        )
    console.print(table)


@app.command()
def dashboard() -> None:
    _not_implemented("Phase 7 (Dashboard)")


if __name__ == "__main__":
    app()

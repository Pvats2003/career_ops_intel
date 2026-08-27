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

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from job_agent.applications.provider import ManualReviewProvider
from job_agent.applications.repository import get_answers
from job_agent.applications.schema import ApplicationStatus
from job_agent.applications.service import prepare_applications_batch, submit_applications_batch
from job_agent.candidate.parser import CandidateParseError, parse_candidate_profile
from job_agent.config.loader import REPO_ROOT, load_config
from job_agent.db.models import Application, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.jobs.service import run_scan
from job_agent.llm.provider import NullLLMProvider, build_llm_provider
from job_agent.logging.setup import configure_logging, get_logger, log_event, redact_text
from job_agent.matching.service import run_matching
from job_agent.resume.errors import ResumeExtractionError
from job_agent.resume.repository import list_versions
from job_agent.resume.service import create_profile_version

app = typer.Typer(help="Autonomous global job discovery and application agent.")
profile_app = typer.Typer(help="Candidate profile commands.")
jobs_app = typer.Typer(help="Job discovery commands (Phase 2+).")
applications_app = typer.Typer(help="Application pipeline commands (Phase 5+).")
app.add_typer(profile_app, name="profile")
app.add_typer(jobs_app, name="jobs")
app.add_typer(applications_app, name="applications")

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
    provider = ManualReviewProvider()

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

        outcomes = prepare_applications_batch(
            session, cfg, items, candidate_id, profile, provider, llm=llm
        )

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
        table.add_row(
            str(item.job.id), item.job.company_name, item.job.title,
            f"[{color}]{item.application.status}[/{color}]", "",
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


@app.command()
def dashboard() -> None:
    _not_implemented("Phase 7 (Dashboard)")


if __name__ == "__main__":
    app()

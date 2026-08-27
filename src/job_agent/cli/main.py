"""job-agent CLI.

Phase 1 implements: init, profile parse, status, health.
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

from job_agent.candidate.parser import CandidateParseError, parse_candidate_profile
from job_agent.config.loader import REPO_ROOT, load_config
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.logging.setup import configure_logging, get_logger, log_event

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
        console.print(f"[red]Failed to parse candidate profile:[/red] {exc}")
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
        checks.append(("config", False, str(exc)))
        cfg = None

    if cfg is not None:
        try:
            parse_candidate_profile(cfg)
            checks.append(("candidate_profile", True, "parses cleanly"))
        except Exception as exc:  # noqa: BLE001
            checks.append(("candidate_profile", False, str(exc)))

        try:
            engine = get_engine(cfg.env.database_url)
            init_db(engine)
            checks.append(("database", True, cfg.env.database_url))
        except Exception as exc:  # noqa: BLE001
            checks.append(("database", False, str(exc)))

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
    _not_implemented("Phase 2 (Job Engine)")


@jobs_app.command("match")
def jobs_match() -> None:
    _not_implemented("Phase 3 (Matching)")


@applications_app.command("prepare")
def applications_prepare() -> None:
    _not_implemented("Phase 5 (Application Engine)")


@applications_app.command("review")
def applications_review() -> None:
    _not_implemented("Phase 7 (Dashboard / Review Queue)")


@applications_app.command("run")
def applications_run() -> None:
    _not_implemented("Phase 6 (Real Application Flows)")


@app.command()
def dashboard() -> None:
    _not_implemented("Phase 7 (Dashboard)")


if __name__ == "__main__":
    app()

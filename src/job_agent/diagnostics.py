"""Shared system diagnostics — `job-agent doctor` (this process/filesystem)
and `/api/health` (a deployed instance, polled by whatever's running it)
both answer the same underlying question through this one module: "is
Career OS actually configured and working right now, and if not, what
exactly needs fixing?" Every check here inspects real config/env/DB
state — nothing is assumed to pass, and NETWORK is always reported UNKNOWN
(never PASS) because nothing here makes an outbound HTTP call to a job
source; reachability can only be verified by actually running a search
(`job-agent jobs search-run`) from wherever Career OS is deployed.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from job_agent.candidate.parser import CandidateParseError, parse_candidate_profile
from job_agent.config.loader import REPO_ROOT, AppConfig, load_config
from job_agent.db.session import get_engine
from job_agent.logging.setup import redact_text

Status = str  # "PASS" | "WARN" | "ERROR" | "UNKNOWN"

_STATUS_ORDER = {"ERROR": 0, "WARN": 1, "UNKNOWN": 2, "PASS": 3}

REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "typer",
    "httpx",
    "anthropic",
    "apscheduler",
    "pydantic",
    "bs4",
    "docx",
)

_PLACEHOLDER_PREFIX = "REPLACE_WITH"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: Status
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def worst_status(self) -> Status:
        return min((c.status for c in self.checks), key=lambda s: _STATUS_ORDER[s], default="PASS")

    @property
    def has_errors(self) -> bool:
        return any(c.status == "ERROR" for c in self.checks)


def _check_python() -> DoctorCheck:
    # Requires-Python in pyproject.toml (>=3.11) already stops `pip install`
    # from succeeding on an older interpreter, so reaching this line at all
    # means the floor is met — this is purely informational.
    version = sys.version.split()[0]
    return DoctorCheck("Python", "PASS", f"{version} (>=3.11 required)")


def _check_dependencies() -> DoctorCheck:
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        return DoctorCheck(
            "Dependencies",
            "ERROR",
            f"missing: {', '.join(missing)} — run `pip install -e .[dev]`",
        )
    return DoctorCheck("Dependencies", "PASS", "all required backend packages importable")


def _find_unknown_fields(model: BaseModel, prefix: str = "") -> list[str]:
    unknown: list[str] = []
    for field_name in type(model).model_fields:
        value = getattr(model, field_name)
        path = f"{prefix}{field_name}"
        if isinstance(value, BaseModel):
            unknown.extend(_find_unknown_fields(value, prefix=f"{path}."))
        elif isinstance(value, str) and value == "UNKNOWN":
            unknown.append(path)
    return unknown


def _check_config(config_dir: Path | None) -> tuple[AppConfig | None, DoctorCheck]:
    try:
        cfg = load_config(config_dir)
    except Exception as exc:  # noqa: BLE001
        return None, DoctorCheck("Configuration", "ERROR", redact_text(str(exc)))
    return cfg, DoctorCheck("Configuration", "PASS", f"loaded from {cfg.env.config_dir}")


def _check_candidate_profile(cfg: AppConfig) -> DoctorCheck:
    try:
        profile = parse_candidate_profile(cfg)
    except CandidateParseError as exc:
        return DoctorCheck("Candidate profile", "ERROR", redact_text(str(exc)))
    except Exception as exc:  # noqa: BLE001
        return DoctorCheck("Candidate profile", "ERROR", redact_text(str(exc)))
    skills = len(profile.skills)
    experience = len(profile.experience)
    if skills == 0 and experience == 0:
        return DoctorCheck(
            "Candidate profile",
            "WARN",
            "parses, but NOT CONFIGURED — no skills or experience found in candidate/*.md",
        )
    return DoctorCheck(
        "Candidate profile", "PASS", f"{skills} skills, {experience} experience entries detected"
    )


def _check_preferences(cfg: AppConfig) -> DoctorCheck:
    unknown = _find_unknown_fields(cfg.preferences)
    if unknown:
        return DoctorCheck(
            "Candidate preferences",
            "WARN",
            f"{len(unknown)} field(s) NOT CONFIGURED in config/preferences.yaml: "
            + ", ".join(unknown),
        )
    return DoctorCheck("Candidate preferences", "PASS", "all fields in config/preferences.yaml set")


@dataclass(frozen=True)
class SchemaRevisionInfo:
    connected: bool
    current_revision: str | None
    head_revision: str | None
    error: str | None = None

    @property
    def up_to_date(self) -> bool:
        return self.connected and self.current_revision == self.head_revision


def _schema_revision_info(database_url: str) -> SchemaRevisionInfo:
    """Real DB connectivity plus a real Alembic revision comparison —
    shared by `job-agent doctor`/`db current` and `/api/health` so both
    answer "is the schema actually current" the same way, not just
    "does a revision exist at all" (which can't distinguish an
    up-to-date database from one that's behind head)."""
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        alembic_cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        head_revision = ScriptDirectory.from_config(alembic_cfg).get_current_head()

        engine = get_engine(database_url)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current_revision = context.get_current_revision()
    except Exception as exc:  # noqa: BLE001
        return SchemaRevisionInfo(
            connected=False, current_revision=None, head_revision=None,
            error=redact_text(str(exc)),
        )
    return SchemaRevisionInfo(
        connected=True, current_revision=current_revision, head_revision=head_revision
    )


def _check_database(cfg: AppConfig) -> DoctorCheck:
    info = _schema_revision_info(cfg.env.database_url)
    safe_url = redact_text(cfg.env.database_url)
    if not info.connected:
        return DoctorCheck("Database", "ERROR", info.error or "connection failed")
    if info.current_revision is None:
        return DoctorCheck(
            "Database", "WARN", f"{safe_url} — not yet initialized, run `job-agent init`"
        )
    if not info.up_to_date:
        return DoctorCheck(
            "Database",
            "WARN",
            f"{safe_url} @ {info.current_revision} — behind head ({info.head_revision}); "
            "run `job-agent db upgrade`",
        )
    return DoctorCheck("Database", "PASS", f"{safe_url} @ {info.current_revision}")


def _check_source(cfg: AppConfig, key: str, *, keyless: bool) -> DoctorCheck:
    source = cfg.sources.sources.get(key)
    label = key.capitalize()
    if source is None:
        return DoctorCheck(label, "ERROR", "missing from config/sources.yaml")
    if not source.enabled:
        return DoctorCheck(label, "WARN", "disabled in config/sources.yaml")
    if keyless:
        return DoctorCheck(label, "PASS", "enabled, no credentials required")
    placeholder_boards = [
        b for b in source.boards if b.token.startswith(_PLACEHOLDER_PREFIX)
    ]
    if placeholder_boards:
        return DoctorCheck(
            label,
            "ERROR",
            "enabled but still has placeholder board token(s) in config/sources.yaml — "
            "replace with a real company token before use",
        )
    return DoctorCheck(label, "PASS", f"enabled, {len(source.boards)} board(s) configured")


def _check_adzuna(cfg: AppConfig) -> DoctorCheck:
    source = cfg.sources.sources.get("adzuna")
    if source is None:
        return DoctorCheck("Adzuna", "ERROR", "missing from config/sources.yaml")
    if not source.enabled:
        return DoctorCheck("Adzuna", "WARN", "disabled in config/sources.yaml")
    if not cfg.env.adzuna_app_id or not cfg.env.adzuna_app_key:
        return DoctorCheck(
            "Adzuna",
            "WARN",
            "enabled but ADZUNA_APP_ID/ADZUNA_APP_KEY not set in .env — free credentials at "
            "https://developer.adzuna.com/",
        )
    return DoctorCheck("Adzuna", "PASS", "enabled, credentials present (not network-verified)")


def _check_anthropic(cfg: AppConfig) -> DoctorCheck:
    if not cfg.env.anthropic_api_key:
        return DoctorCheck(
            "Anthropic (LLM)",
            "WARN",
            "ANTHROPIC_API_KEY not set — deterministic-only matching/tailoring; no LLM features",
        )
    return DoctorCheck(
        "Anthropic (LLM)", "PASS", "ANTHROPIC_API_KEY set (key validity not network-verified)"
    )


def _check_frontend() -> DoctorCheck:
    dist_index = REPO_ROOT / "web-ui" / "dist" / "index.html"
    if dist_index.exists():
        return DoctorCheck("Frontend build", "PASS", f"built bundle found at {dist_index}")
    return DoctorCheck(
        "Frontend build",
        "WARN",
        "no build found — run `cd web-ui && npm install && npm run build`, "
        "or `npm run dev` for local development",
    )


def _check_scheduler() -> DoctorCheck:
    if importlib.util.find_spec("apscheduler") is None:
        return DoctorCheck("Scheduler", "ERROR", "apscheduler not installed")
    return DoctorCheck(
        "Scheduler",
        "PASS",
        "apscheduler installed — runs inside `job-agent serve` (default 24h "
        "search_frequency_hours, configurable from the Settings page)",
    )


def _check_network() -> DoctorCheck:
    return DoctorCheck(
        "Network (job sources)",
        "UNKNOWN",
        "not checked — doctor makes no outbound calls; verify with "
        "`job-agent jobs search-run` on the machine Career OS will actually run on",
    )


def get_health_status(cfg: AppConfig) -> dict:
    """Machine-readable status for `/api/health` — deliberately a SMALLER
    set of checks than `run_doctor()` (no filesystem/Python-version/
    dependency checks; those only matter to someone with a shell on the
    box, never to whatever's polling a deployed instance's health
    endpoint). Every value here is a plain bool/string derived from
    config/DB state — never a raw `database_url`, API key, or credential,
    so this is always safe to expose on a public health endpoint."""
    schema = _schema_revision_info(cfg.env.database_url)

    def _source_status(key: str, *, keyless: bool) -> str:
        source = cfg.sources.sources.get(key)
        if source is None:
            return "missing_config"
        if not source.enabled:
            return "disabled"
        if keyless:
            return "enabled"
        if key == "adzuna":
            has_credentials = cfg.env.adzuna_app_id and cfg.env.adzuna_app_key
            return "enabled" if has_credentials else "enabled_no_credentials"
        placeholder = any(b.token.startswith(_PLACEHOLDER_PREFIX) for b in source.boards)
        return "enabled_placeholder_token" if placeholder else "enabled"

    return {
        "status": "ok",
        "database": {
            "connected": schema.connected,
            "migrations_current": schema.up_to_date,
        },
        "scheduler": {
            "available": importlib.util.find_spec("apscheduler") is not None,
        },
        "job_sources": {
            "remotive": _source_status("remotive", keyless=True),
            "arbeitnow": _source_status("arbeitnow", keyless=True),
            "adzuna": _source_status("adzuna", keyless=False),
            "greenhouse": _source_status("greenhouse", keyless=False),
            "lever": _source_status("lever", keyless=False),
        },
        "llm": {
            "configured": bool(cfg.env.anthropic_api_key),
        },
    }


def run_doctor(config_dir: Path | None = None) -> DoctorReport:
    checks: list[DoctorCheck] = [_check_python(), _check_dependencies()]

    cfg, config_check = _check_config(config_dir)
    checks.append(config_check)

    if cfg is not None:
        checks.append(_check_database(cfg))
        checks.append(_check_candidate_profile(cfg))
        checks.append(_check_preferences(cfg))
        checks.append(_check_source(cfg, "remotive", keyless=True))
        checks.append(_check_source(cfg, "arbeitnow", keyless=True))
        checks.append(_check_adzuna(cfg))
        checks.append(_check_source(cfg, "greenhouse", keyless=False))
        checks.append(_check_source(cfg, "lever", keyless=False))
        checks.append(_check_anthropic(cfg))

    checks.append(_check_frontend())
    checks.append(_check_scheduler())
    checks.append(_check_network())

    return DoctorReport(checks=tuple(checks))

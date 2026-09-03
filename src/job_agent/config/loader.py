"""Loads and validates config/*.yaml plus environment-derived settings.

Design notes
------------
* YAML files hold non-secret, human-editable preferences and rules — see
  BUILD PROMPT section 38. They are validated against the models in
  ``job_agent.config.models`` so a typo fails fast at startup.
* Secrets (API keys, DB URLs) and environment-level toggles (DRY_RUN,
  LIVE_MODE) come from environment variables / ``.env`` via
  ``pydantic-settings``, never from the YAML files, and are never logged.
* ``DRY_RUN``/``LIVE_MODE`` env vars, when set, OVERRIDE the YAML values in
  automation.yaml — the environment is the safety-critical source of truth
  for whether the system is allowed to submit anything for real.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_agent.config.models import (
    AutomationConfig,
    PreferencesConfig,
    ProfileConfig,
    RulesConfig,
    SourcesConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_CANDIDATE_DIR = REPO_ROOT / "candidate"


class EnvSettings(BaseSettings):
    """Environment-derived settings. Never printed or logged verbatim."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config_dir: Path = DEFAULT_CONFIG_DIR
    candidate_dir: Path = DEFAULT_CANDIDATE_DIR
    database_url: str = Field(default="sqlite:///./data/job_agent.db")
    log_level: str = "INFO"
    log_format: str = "json"

    # Safety-critical overrides. None => "not set, defer to automation.yaml".
    dry_run: bool | None = None
    live_mode: bool | None = None

    anthropic_api_key: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None

    # Adzuna Jobs API (Phase 8's multi-country search_api source) — free
    # credentials from https://developer.adzuna.com/. Left unset means the
    # `adzuna` source, even if `enabled: true` in sources.yaml, is skipped
    # with a logged reason rather than making an unauthenticated call.
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Required config file missing: {path}. "
            "Run `job-agent init` to scaffold default config."
        )
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level")
    return data


class AppConfig:
    """Fully validated, merged application configuration.

    Composition over a single flat model is deliberate: each YAML file is
    independently owned/edited by the candidate and validated in isolation,
    so one bad file doesn't block loading the others' error messages.
    """

    def __init__(
        self,
        env: EnvSettings,
        profile: ProfileConfig,
        preferences: PreferencesConfig,
        sources: SourcesConfig,
        automation: AutomationConfig,
        rules: RulesConfig,
    ) -> None:
        self.env = env
        self.profile = profile
        self.preferences = preferences
        self.sources = sources
        self.automation = automation
        self.rules = rules

    @property
    def dry_run(self) -> bool:
        """Effective dry-run state: env var overrides YAML; default safe (True)."""
        if self.env.dry_run is not None:
            return self.env.dry_run
        return self.automation.dry_run

    @property
    def live_mode(self) -> bool:
        """Effective live-mode state: env var overrides YAML; default safe (False)."""
        if self.env.live_mode is not None:
            return self.env.live_mode
        return self.automation.live_mode

    def is_submission_allowed(self) -> bool:
        """Single choke point every submission path must consult.

        Submission is allowed only when dry_run is explicitly disabled AND
        live_mode is explicitly enabled. Either safety switch alone is not
        enough — see BUILD PROMPT sections 36-37.
        """
        return (not self.dry_run) and self.live_mode


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Load, validate, and merge all configuration sources.

    Raises on any missing/invalid file rather than silently defaulting —
    a broken config must never fall back to unsafe behavior.
    """
    env = EnvSettings()
    cfg_dir = config_dir or env.config_dir

    profile = ProfileConfig.model_validate(_load_yaml(cfg_dir / "profile.yaml"))
    preferences = PreferencesConfig.model_validate(_load_yaml(cfg_dir / "preferences.yaml"))
    sources = SourcesConfig.model_validate(_load_yaml(cfg_dir / "sources.yaml"))
    automation = AutomationConfig.model_validate(_load_yaml(cfg_dir / "automation.yaml"))
    rules = RulesConfig.model_validate(_load_yaml(cfg_dir / "rules.yaml"))

    return AppConfig(
        env=env,
        profile=profile,
        preferences=preferences,
        sources=sources,
        automation=automation,
        rules=rules,
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Process-wide cached config accessor for application code."""
    return load_config()

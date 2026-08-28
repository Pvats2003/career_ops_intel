"""Typed models for the contents of config/*.yaml.

These models exist so that a malformed config file fails fast, at startup,
with a clear validation error — instead of surfacing as a confusing runtime
KeyError deep inside the matching or application engine.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model that rejects unknown keys so config typos are caught."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# profile.yaml
# --------------------------------------------------------------------------
class TargetRoles(StrictModel):
    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)
    exploratory: list[str] = Field(default_factory=list)


class ProfileConfig(StrictModel):
    target_roles: TargetRoles
    target_industries: list[str] = Field(default_factory=list)
    excluded_roles: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    seniority_level: str = "entry_level"


# --------------------------------------------------------------------------
# preferences.yaml
# --------------------------------------------------------------------------
class WorkPreferences(StrictModel):
    remote: str = "UNKNOWN"
    employment_types: list[str] = Field(default_factory=list)
    willing_to_relocate: str = "UNKNOWN"
    notice_period: str = "UNKNOWN"


class LocationPreferences(StrictModel):
    current_location: str = "UNKNOWN"
    preferred_locations: list[str] = Field(default_factory=list)
    open_to_countries: str = "UNKNOWN"


class SalaryPreferences(StrictModel):
    currency: str = "UNKNOWN"
    minimum_annual: str = "UNKNOWN"
    target_annual: str = "UNKNOWN"
    negotiable: str = "UNKNOWN"


class VisaInformation(StrictModel):
    nationality: str = "UNKNOWN"
    requires_sponsorship_us: str = "UNKNOWN"
    requires_sponsorship_uk: str = "UNKNOWN"
    requires_sponsorship_eu: str = "UNKNOWN"
    requires_sponsorship_other: str = "UNKNOWN"
    currently_authorized_countries: list[str] = Field(default_factory=list)


class Availability(StrictModel):
    earliest_start_date: str = "UNKNOWN"


class PreferencesConfig(StrictModel):
    work_preferences: WorkPreferences
    location_preferences: LocationPreferences
    salary_preferences: SalaryPreferences
    visa_information: VisaInformation
    availability: Availability


# --------------------------------------------------------------------------
# sources.yaml
# --------------------------------------------------------------------------
class BoardIdentifier(StrictModel):
    """One company's board within an ATS-API source.

    Field names are generic across ATS kinds: `token` is the Greenhouse
    board token or Lever company slug; `company_name` is supplied
    explicitly by the human rather than inferred from the token, since some
    list endpoints don't reliably return a display name.
    """

    token: str
    company_name: str


class SourceConfig(StrictModel):
    enabled: bool = False
    kind: Literal["ats_api", "scrape", "restricted"] = "restricted"
    poll_interval_minutes: int | None = None
    rate_limit_per_minute: int | None = None
    notes: str = ""
    boards: list[BoardIdentifier] = Field(default_factory=list)


class GlobalLimits(StrictModel):
    max_concurrent_sources: int = 3
    default_backoff_seconds: float = 5
    default_backoff_multiplier: float = 2.0
    default_backoff_max_seconds: float = 300
    max_retries_per_request: int = 3


class SourcesConfig(StrictModel):
    sources: dict[str, SourceConfig]
    global_limits: GlobalLimits


# --------------------------------------------------------------------------
# automation.yaml
# --------------------------------------------------------------------------
class AutomationSettings(StrictModel):
    level: int = Field(ge=0, le=4, default=3)
    mode: str = "human_approval"


class MatchingThresholds(StrictModel):
    auto_apply_threshold: int = Field(ge=0, le=100, default=90)
    review_threshold: int = Field(ge=0, le=100, default=80)
    save_threshold: int = Field(ge=0, le=100, default=70)
    semantic_blend_weight: float = Field(ge=0.0, le=1.0, default=0.4)


class FreshnessSettings(StrictModel):
    preferred_hours: int = 24
    just_posted_hours: int = 6
    recent_days: int = 7


class PriorityWeights(StrictModel):
    match: float = 0.50
    freshness: float = 0.20
    career_value: float = 0.15
    company_fit: float = 0.10
    application_ease: float = 0.05


class ScoringWeights(StrictModel):
    skills: float = 0.25
    experience: float = 0.20
    role_alignment: float = 0.20
    projects: float = 0.10
    education: float = 0.10
    location: float = 0.05
    seniority: float = 0.05
    eligibility: float = 0.05


class ApplicationLimits(StrictModel):
    max_per_day: int = 15
    max_per_hour: int = 5
    max_per_company: int = 1
    max_per_source_per_day: int = 10


class SchedulerSettings(StrictModel):
    job_discovery_minutes: int = 10
    analytics_daily_hour_utc: int = 2
    cleanup_daily_hour_utc: int = 3


class LLMSettings(StrictModel):
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    max_requests_per_minute: int = 20


# --------------------------------------------------------------------------
# Application-provider selection (Phase 6B CLI wiring). Mirrors sources.
# yaml's per-source `enabled: false` opt-in pattern exactly:
# `manual_review` (the only provider in production before this phase) stays
# the default so no existing behavior changes unless a config explicitly
# selects otherwise. `structured_ats` additionally requires its own nested
# `enabled: true` — two switches, not one, matching the same
# defense-in-depth posture `AppConfig.is_submission_allowed()` already uses
# for dry_run/live_mode.
# --------------------------------------------------------------------------
class StructuredATSProviderConfig(StrictModel):
    enabled: bool = False
    # Relative to the repo root; points at a LOCAL fixture file only — see
    # config/fixtures/structured_ats_forms.example.yaml. Never a URL, never
    # anything fetched over the network.
    fixture_path: str = "config/fixtures/structured_ats_forms.example.yaml"


# --------------------------------------------------------------------------
# Real-submission-capable provider selection (Phase 6C). Mirrors
# `StructuredATSProviderConfig`'s exact "enabled: false" opt-in pattern —
# and adds a third, independent gate on top: `credential_env_var` only
# NAMES an environment variable; it never carries a secret value itself,
# and `job_agent.security.credentials.EnvCredentialStore` (the only thing
# that ever reads it) raises rather than proceeds if that variable isn't
# actually set. So even `provider: "real_structured_ats"` +
# `enabled: true` together are not sufficient for a real submission to
# occur — a real credential must ALSO be configured (Stage 2, never this
# phase), on top of `job_agent.applications.service.submit_application`'s
# allowlist+approval gate, on top of `dry_run`/`live_mode`. No shipped
# config in this repository sets `provider` to this value.
# --------------------------------------------------------------------------
class RealStructuredATSProviderConfig(StrictModel):
    enabled: bool = False
    # Relative to the repo root; points at a LOCAL fixture file only — see
    # config/fixtures/real_structured_ats_forms.example.yaml. Never a URL.
    fixture_path: str = "config/fixtures/real_structured_ats_forms.example.yaml"
    # The name `RealStructuredATSProvider` asks its `CredentialProvider`
    # for — never a secret value itself.
    credential_name: str = "real_structured_ats_credential"
    # NAMES an environment variable; never the credential's value. See
    # `job_agent.security.credentials.EnvCredentialStore`.
    credential_env_var: str = "JOB_AGENT_REAL_STRUCTURED_ATS_CREDENTIAL"


# --------------------------------------------------------------------------
# Browser-automation provider selection (Phase 6D). Mirrors
# `StructuredATSProviderConfig`'s exact "enabled: false" opt-in pattern.
# `BrowserApplicationProvider` has no local-simulation mode — it always
# inspects a live DOM — so `target_urls_path` is NOT simulated form data
# like the other two providers' fixtures; it is a curated ALLOWLIST of
# approved `application_url` values. A job whose `application_url` isn't
# on this list is never handed to the provider at all. Selecting this
# provider also requires a live `playwright.sync_api.Browser` to be
# passed to `build_application_provider(..., browser=...)` explicitly —
# no caller in this repository does that yet, so enabling this provider
# today fails clearly and safely rather than silently doing anything.
# No shipped config in this repository sets `provider` to this value.
# --------------------------------------------------------------------------
class BrowserApplicationProviderConfig(StrictModel):
    enabled: bool = False
    # Relative to the repo root; points at a LOCAL fixture file only — see
    # config/fixtures/browser_application_targets.example.yaml. Never a
    # URL fetched over the network; only ever read from disk.
    target_urls_path: str = "config/fixtures/browser_application_targets.example.yaml"


class ApplicationProviderConfig(StrictModel):
    provider: Literal[
        "manual_review", "structured_ats", "real_structured_ats", "browser_application"
    ] = "manual_review"
    structured_ats: StructuredATSProviderConfig = Field(
        default_factory=StructuredATSProviderConfig
    )
    real_structured_ats: RealStructuredATSProviderConfig = Field(
        default_factory=RealStructuredATSProviderConfig
    )
    browser_application: BrowserApplicationProviderConfig = Field(
        default_factory=BrowserApplicationProviderConfig
    )


class AutomationConfig(StrictModel):
    automation: AutomationSettings
    dry_run: bool = True
    live_mode: bool = False
    matching: MatchingThresholds
    freshness: FreshnessSettings
    priority_weights: PriorityWeights
    scoring_weights: ScoringWeights
    applications: ApplicationLimits
    scheduler: SchedulerSettings
    llm: LLMSettings
    application_provider: ApplicationProviderConfig = Field(
        default_factory=ApplicationProviderConfig
    )


# --------------------------------------------------------------------------
# rules.yaml
# --------------------------------------------------------------------------
class SafetyRules(StrictModel):
    never_fabricate: bool = True
    human_review_unknown: bool = True
    human_review_ambiguous: bool = True
    stop_on_captcha: bool = True
    stop_on_mfa: bool = True
    stop_on_unexpected_form: bool = True
    stop_on_consent_required: bool = True
    never_bypass_access_controls: bool = True
    never_bypass_rate_limits: bool = True
    never_bypass_bot_detection: bool = True


class TruthValidationRules(StrictModel):
    allowed_fact_statuses: list[str]
    internal_only_statuses: list[str]
    blocked_statuses: list[str]


class LoggingRules(StrictModel):
    redact_fields: list[str] = Field(default_factory=list)


class RulesConfig(StrictModel):
    safety: SafetyRules
    hard_stop_conditions: list[str]
    truth_validation: TruthValidationRules
    logging: LoggingRules

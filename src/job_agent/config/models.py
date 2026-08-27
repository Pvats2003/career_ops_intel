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
    model: str = "configurable"
    max_requests_per_minute: int = 20


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

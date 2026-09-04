"""API response/request models for the Career OS web dashboard.

Deliberately separate from `job_agent.db.models` (ORM rows are never
returned directly) and from `job_agent.candidate.schema`/`job_agent.
matching.schema` (those stay the internal contract other services build
against) — this module is the one place the HTTP wire format is allowed
to drift from either without touching business logic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Candidate / resume
# --------------------------------------------------------------------------


class CandidateProfileOut(BaseModel):
    candidate_id: int
    name: str
    email: str
    phone: str
    linkedin: str
    current_location: str
    years_experience: float
    target_roles_primary: list[str]
    target_roles_secondary: list[str]
    skills: list[str]
    technical_skills: list[str]
    experience: list[dict]
    education: list[dict]
    projects: list[dict]
    achievements: list[dict]
    certifications: list[dict]
    source_files: list[str]
    parsed_at: datetime


class ResumeUploadResult(BaseModel):
    saved_path: str
    profile_version_id: int | None
    validation_status: str
    issues: list[str]


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


class MatchOut(BaseModel):
    overall_score: int
    decision: str
    skills_match: int
    experience_match: int
    role_match: int
    project_match: int
    education_match: int
    location_match: int
    seniority_match: int
    eligibility_match: int
    missing_requirements: list[str]
    concerns: list[str]
    hard_stop_reasons: list[str]
    excluded_reasons: list[str]
    reasoning: str
    semantic_available: bool


class DataConfidenceOut(BaseModel):
    """Confidence in the underlying DATA, separate from the match score —
    Career OS FINAL GOD MODE Part 3.8. Prevents false precision: a 91
    match score built on an unverified posting date and no salary is
    still a 91, but the candidate should know which facts are shaky."""

    level: str  # "High" | "Medium"
    reasons: list[str]


class ApplicationViabilityOut(BaseModel):
    """Practical, mechanical readiness to apply — Part 3.9. Computed
    entirely from stored data (no live network check); see
    `URLCheckResultOut` for the one live check, triggered on demand."""

    url_exists: bool
    direct_application: bool
    job_active: bool
    qualifications_status: str  # "MEETS" | "GAPS" | "UNKNOWN"
    location_compatible: bool | None
    visa_info_available: bool
    overall: str  # "VIABLE" | "CAUTION" | "BLOCKED"
    reasons: list[str]


class URLCheckResultOut(BaseModel):
    status: str  # "REACHABLE" | "UNREACHABLE" | "UNKNOWN"
    detail: str
    checked_at: datetime


class JobOut(BaseModel):
    id: int
    title: str
    company_name: str
    location: str | None
    remote_type: str | None
    employment_type: str | None
    salary_min: float | None
    salary_max: float | None
    currency: str | None
    application_url: str | None
    posted_at: datetime | None
    discovered_at: datetime
    freshness_status: str
    freshness_label: str
    source_name: str | None
    match: MatchOut | None
    pipeline_stage: str | None
    application_id: int | None
    lifecycle_status: str
    # Cross-source duplicate canonicalization (section 8): this JobOut is
    # the ONE canonical representative for every Job row sharing its
    # content fingerprint. also_seen_on lists the OTHER sources that also
    # carried this same posting — never a separate card in the UI.
    also_seen_on: list[str]
    duplicate_count: int
    data_confidence: DataConfidenceOut
    viability: ApplicationViabilityOut


class JobDetailOut(JobOut):
    description: str | None
    requirements: str | None
    preferred_qualifications: str | None
    visa_information: str | None
    company_url: str | None


class JobListOut(BaseModel):
    total: int
    items: list[JobOut]


class ScanSourceResultOut(BaseModel):
    source_name: str
    identifier: str
    fetched: int
    created: int
    updated: int
    errors: list[str]


class ScanRunOut(BaseModel):
    results: list[ScanSourceResultOut]
    enabled_sources: int


class MatchRunOut(BaseModel):
    matched: int
    apply_count: int
    review_count: int
    save_count: int
    skip_count: int
    human_required_count: int


# --------------------------------------------------------------------------
# Pipeline / applications
# --------------------------------------------------------------------------

PIPELINE_STAGES: tuple[str, ...] = (
    "SAVED",
    "SHORTLISTED",
    "APPLY",
    "APPLIED",
    "ASSESSMENT",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
)


class ApplicationScorecardOut(BaseModel):
    candidate_fit: float
    job_quality: float
    career_value: float
    application_viability: float
    overall_score: float
    overall_recommendation: str


class ApplicationChecklistOut(BaseModel):
    resume_selected: bool
    resume_tailored: bool
    cover_letter_ready: bool
    questions_prepared: bool
    submitted: bool
    confirmation_received: bool


class ApplicationHistoryEventOut(BaseModel):
    event_type: str
    details: dict
    created_at: datetime


class PipelineItemOut(BaseModel):
    application_id: int
    job: JobOut
    pipeline_stage: str
    status: str
    notes: str | None
    recruiter_contact: str | None
    interview_date: datetime | None
    follow_up_date: datetime | None
    outcome: str | None
    created_at: datetime
    updated_at: datetime
    scorecard: ApplicationScorecardOut
    checklist: ApplicationChecklistOut


class PipelineUpdateIn(BaseModel):
    pipeline_stage: str | None = Field(default=None)
    notes: str | None = None
    recruiter_contact: str | None = None
    interview_date: datetime | None = None
    follow_up_date: datetime | None = None
    outcome: str | None = None
    cover_letter_ready: bool | None = None
    questions_prepared: bool | None = None


# --------------------------------------------------------------------------
# Dashboard / analytics
# --------------------------------------------------------------------------


class DashboardSummaryOut(BaseModel):
    resume_parsed: bool
    resume_validation_status: str | None
    job_matches: int
    shortlisted: int
    applied: int
    interviewing: int
    offers: int
    total_jobs_discovered: int
    apply_priority_count: int
    top_opportunities: list[JobOut]


class StageBreakdownOut(BaseModel):
    stage: str
    count: int


class CareerPathAnalyticsOut(BaseModel):
    label: str
    applications: int
    interviews: int
    offers: int
    interview_rate: float


class AnalyticsOut(BaseModel):
    stage_breakdown: list[StageBreakdownOut]
    total_jobs_discovered: int
    total_matched: int
    total_shortlisted: int
    total_applied: int
    total_interviews: int
    total_offers: int
    total_rejections: int
    application_rate: float
    interview_rate: float
    offer_rate: float
    by_company: list[CareerPathAnalyticsOut]


# --------------------------------------------------------------------------
# Application assistant (section 15) — never persisted in V1, generated
# fresh from the truthful answer_engine each call.
# --------------------------------------------------------------------------


class AssistantAnswerOut(BaseModel):
    question: str
    category: str
    answer: str | None
    confidence: float
    source: str
    requires_human: bool
    validation_notes: list[str]


class AssistantResponseOut(BaseModel):
    job_id: int
    answers: list[AssistantAnswerOut]


class AssistantQuestionsIn(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=20)


# --------------------------------------------------------------------------
# Career path discovery (section 5)
# --------------------------------------------------------------------------


class CareerPathOut(BaseModel):
    label: str
    fit_score: int
    evidence: list[str]
    relevant_skills: list[str]
    relevant_experience: list[str]
    missing_skills: list[str]
    typical_titles: list[str]
    career_upside: str
    recommended_priority: str


class CareerProfileOut(BaseModel):
    primary_direction: str | None
    strengths: list[str]
    growing_area: str | None
    skill_gaps: list[str]
    best_locations: list[str]


class CareerPathComparisonRowOut(BaseModel):
    label: str
    current_fit: int
    job_volume: int
    career_upside: str
    skill_gap: str
    interview_rate: float | None
    interview_sample_size: int
    overall: int


class SkillGapEntryOut(BaseModel):
    skill: str
    frequency_count: int
    frequency_pct: float
    unlocks_count: int
    relevant_career_paths: list[str]


# --------------------------------------------------------------------------
# Resume tailoring / cover letter / (assistant is above)
# --------------------------------------------------------------------------


class TailoredResumeOut(BaseModel):
    job_id: int
    professional_summary: str
    relevant_skills: list[str]
    emphasized_experience: list[dict]
    relevant_projects: list[dict]
    ats_keywords: list[str]
    notes: list[str]
    generated_by: str  # "llm" | "deterministic"


class CoverLetterOut(BaseModel):
    job_id: int
    body: str
    notes: list[str]
    generated_by: str  # "llm" | "deterministic"


# --------------------------------------------------------------------------
# Company intelligence (Phase 10)
# --------------------------------------------------------------------------


class CompanyOut(BaseModel):
    id: int
    name: str
    industry: str | None
    size: str | None
    website: str | None
    career_page_url: str | None
    notes: str | None
    open_roles: int
    matching_jobs: list[JobOut]
    company_fit: int | None
    company_fit_reasons: list[str]


# --------------------------------------------------------------------------
# Watchlist (Phase 11 section 19)
# --------------------------------------------------------------------------

WATCHLIST_KINDS: tuple[str, ...] = ("COMPANY", "ROLE", "LOCATION")


class WatchlistEntryOut(BaseModel):
    id: int
    kind: str
    value: str
    created_at: datetime


class WatchlistEntryIn(BaseModel):
    kind: str
    value: str


# --------------------------------------------------------------------------
# Notifications (Phase 11 section 20)
# --------------------------------------------------------------------------


class NotificationOut(BaseModel):
    id: int
    event_type: str
    title: str
    message: str
    related_job_id: int | None
    related_application_id: int | None
    read_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------------
# Search preferences (Phase 15 settings page)
# --------------------------------------------------------------------------


class SearchPreferencesOut(BaseModel):
    target_roles: list[str]
    target_countries: list[str]
    target_cities: list[str]
    remote_preference: str | None
    min_salary: float | None
    max_experience_gap_years: float | None
    industries: list[str]
    companies_priority: list[str]
    companies_excluded: list[str]
    min_match_score: int
    search_frequency_hours: int
    notification_min_score: int
    notification_frequency: str


class SearchPreferencesIn(BaseModel):
    target_roles: list[str] | None = None
    target_countries: list[str] | None = None
    target_cities: list[str] | None = None
    remote_preference: str | None = None
    min_salary: float | None = None
    max_experience_gap_years: float | None = None
    industries: list[str] | None = None
    companies_priority: list[str] | None = None
    companies_excluded: list[str] | None = None
    min_match_score: int | None = None
    search_frequency_hours: int | None = None
    notification_min_score: int | None = None
    notification_frequency: str | None = None


SUPPORTED_COUNTRIES: tuple[str, ...] = (
    "India",
    "USA",
    "Canada",
    "UK",
    "Germany",
    "Netherlands",
    "Ireland",
    "Singapore",
    "UAE",
    "Australia",
    "Remote",
    "Worldwide",
)


# --------------------------------------------------------------------------
# Search runs (Phase 8 section 3)
# --------------------------------------------------------------------------


class SearchRunOut(BaseModel):
    id: int
    started_at: datetime
    completed_at: datetime | None
    sources: list[str]
    queries: list[str]
    jobs_found: int
    duplicates_removed: int
    expired_removed: int
    qualified: int
    errors: list[str]
    status: str


# --------------------------------------------------------------------------
# Ranking: Today's Top 10 / Apply Now (section 9-10)
# --------------------------------------------------------------------------


class RankedJobOut(BaseModel):
    job: JobOut
    rank_score: float
    why: list[str]
    gaps: list[str]
    recommendation: str


class NewSinceLastVisitOut(BaseModel):
    previous_visit_at: datetime | None
    jobs: list[RankedJobOut]


# --------------------------------------------------------------------------
# Follow-up intelligence (Phase 13)
# --------------------------------------------------------------------------


class FollowUpMessageOut(BaseModel):
    subject: str
    body: str


class FollowUpRecommendationOut(BaseModel):
    application_id: int
    job: JobOut
    applied_days_ago: int
    suggested_action: str
    message: FollowUpMessageOut


# --------------------------------------------------------------------------
# Morning briefing (FINAL GOD MODE Part 1.3)
# --------------------------------------------------------------------------


class BriefingHighlightOut(BaseModel):
    job_id: int
    title: str
    company: str
    location: str | None
    rank_score: float
    freshness_label: str
    why: str | None


class MorningBriefingOut(BaseModel):
    total_opportunities: int
    exceptional_count: int
    strong_count: int
    possible_count: int
    top_highlights: list[BriefingHighlightOut]
    follow_up_summaries: list[str]
    career_insight: str | None
    recommendation: str | None


# --------------------------------------------------------------------------
# Learning / insights (Phase 12)
# --------------------------------------------------------------------------


class CategoryInsightOut(BaseModel):
    category: str
    saved: int
    ignored: int
    applied: int
    save_rate: float
    explanation: str


class InsightsOut(BaseModel):
    categories: list[CategoryInsightOut]
    summary: list[str]

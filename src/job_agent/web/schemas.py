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


class PipelineUpdateIn(BaseModel):
    pipeline_stage: str | None = Field(default=None)
    notes: str | None = None
    recruiter_contact: str | None = None
    interview_date: datetime | None = None
    follow_up_date: datetime | None = None
    outcome: str | None = None


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

"""SQLAlchemy ORM schema.

Implements the minimum tables from BUILD PROMPT section 21:
candidate, candidate_facts, skills, experiences, projects, jobs,
job_sources, job_matches, resumes, applications, application_answers,
application_events, companies, notifications, system_events.

Phase 1 only writes to `candidate`, `candidate_facts`, `skills`,
`experiences`, `projects`, and `system_events` (via the profile ingestion
pipeline and CLI). The remaining tables are defined now — schema and code
evolve together — but are populated starting in Phase 2 (jobs) onward.

All timestamps are stored as timezone-aware UTC (section 52); conversion to
the user's local timezone happens only at presentation time, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------
# Candidate knowledge base
# --------------------------------------------------------------------------
class Candidate(Base, TimestampMixin):
    __tablename__ = "candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(64))
    linkedin: Mapped[str] = mapped_column(String(255))
    current_location: Mapped[str] = mapped_column(String(255))
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_files: Mapped[list] = mapped_column(JSON, default=list)

    facts: Mapped[list[CandidateFact]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    skills: Mapped[list[Skill]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    experiences: Mapped[list[Experience]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class CandidateFact(Base, TimestampMixin):
    """Generic provenance-tracked fact store.

    Used for anything that doesn't warrant its own dedicated table
    (education, certifications, achievements, target roles, preferences,
    visa information). `fact_type` groups related facts; `key`/`value` hold
    the actual datum. Every row carries provenance per section 3.
    """

    __tablename__ = "candidate_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"))
    fact_type: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float)
    verified: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate: Mapped[Candidate] = relationship(back_populates="facts")


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64))
    evidence_level: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float)
    verified: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate: Mapped[Candidate] = relationship(back_populates="skills")


class Experience(Base, TimestampMixin):
    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    start_date: Mapped[str] = mapped_column(String(32))
    end_date: Mapped[str] = mapped_column(String(32))
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    highlights: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    verified: Mapped[bool] = mapped_column(default=True)

    candidate: Mapped[Candidate] = relationship(back_populates="experiences")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(128))
    project_type: Mapped[str] = mapped_column(String(128))
    stack: Mapped[str | None] = mapped_column(String(255), nullable=True)
    highlights: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    verified: Mapped[bool] = mapped_column(default=True)

    candidate: Mapped[Candidate] = relationship(back_populates="projects")


# --------------------------------------------------------------------------
# Companies
# --------------------------------------------------------------------------
class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    career_page_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------
# Job discovery (Phase 2+)
# --------------------------------------------------------------------------
class JobSource(Base, TimestampMixin):
    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(default=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_fingerprint", "job_fingerprint"),
        Index("ix_jobs_company_name", "company_name"),
        Index("ix_jobs_title", "title"),
        Index("ix_jobs_posted_at", "posted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("job_sources.id"), nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_qualifications: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    remote_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    visa_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    application_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    company_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job_fingerprint: Mapped[str] = mapped_column(String(128))
    freshness_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN_POST_DATE")
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)


class JobMatch(Base, TimestampMixin):
    __tablename__ = "job_matches"
    __table_args__ = (
        Index("ix_job_matches_score", "overall_score"),
        Index("ix_job_matches_decision", "decision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"), index=True)
    overall_score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(32))
    skills_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    role_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    project_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    education_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    seniority_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    eligibility_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_requirements: Mapped[list] = mapped_column(JSON, default=list)
    concerns: Mapped[list] = mapped_column(JSON, default=list)
    hard_stop_reasons: Mapped[list] = mapped_column(JSON, default=list)
    excluded_reasons: Mapped[list] = mapped_column(JSON, default=list)
    semantic_available: Mapped[bool] = mapped_column(default=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)


# --------------------------------------------------------------------------
# Resumes and applications (Phase 4+ / 5+)
# --------------------------------------------------------------------------
class Resume(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"), index=True)
    variant_name: Mapped[str] = mapped_column(String(64))
    file_path: Mapped[str] = mapped_column(String(1024))
    is_tailored: Mapped[bool] = mapped_column(default=False)
    tailored_for_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    tailoring_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated: Mapped[bool] = mapped_column(default=False)


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_status", "status"),
        Index("ix_applications_match_score", "match_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id"), index=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED")
    automation_level_used: Mapped[int | None] = mapped_column(nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    confirmation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApplicationAnswer(Base, TimestampMixin):
    __tablename__ = "application_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    question_text: Mapped[str] = mapped_column(Text)
    question_category: Mapped[str] = mapped_column(String(32))
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    requires_human: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ApplicationEvent(Base):
    """Immutable audit trail entry — see BUILD PROMPT section 53."""

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Notifications and system observability
# --------------------------------------------------------------------------
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    related_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    related_application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemEvent(Base):
    """Structured observability log, mirrored to stdout — see section 34."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    result: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

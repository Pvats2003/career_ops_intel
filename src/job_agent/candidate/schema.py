"""Canonical candidate knowledge-base schema.

This is the structured representation the rest of the system reasons about
— the matching engine, resume tailoring, and answer generation must never
read `candidate/*.md` directly; they consume a `CandidateProfile` built by
`job_agent.candidate.parser.parse_candidate_profile()`.

CORE RULE (BUILD PROMPT section 2 and 3): every fact carries provenance
(`source`, `confidence`, `verified`). An LLM-generated inference must never
silently become a verified fact — anything not traceable to a source file or
an explicit human-provided config value is represented as the literal string
``"UNKNOWN"`` with ``confidence=0.0`` and ``verified=False``, never guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

UNKNOWN = "UNKNOWN"

T = TypeVar("T")


class EvidenceLevel(StrEnum):
    """How strongly the candidate knowledge base supports a claim.

    HAS / DEMONSTRATED / ADJACENT are levels a *stored* fact may carry.
    MISSING / UNKNOWN are only ever produced at job-matching time (Phase 3)
    when comparing a job's requirements against the candidate profile — they
    are never written into the candidate knowledge base itself, since there
    is nothing to store for a skill the candidate doesn't have.
    """

    HAS = "HAS"
    DEMONSTRATED = "DEMONSTRATED"
    ADJACENT = "ADJACENT"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


STORABLE_EVIDENCE_LEVELS = frozenset(
    {EvidenceLevel.HAS, EvidenceLevel.DEMONSTRATED, EvidenceLevel.ADJACENT}
)


class Fact(BaseModel, Generic[T]):
    """A single piece of candidate information with full provenance.

    Example (mirrors BUILD PROMPT section 3):
        Fact(value="Python", source="candidate/skills.md", confidence=1.0, verified=True)
    """

    model_config = ConfigDict(frozen=True)

    value: T
    source: str
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool
    note: str | None = None

    @classmethod
    def unknown(cls, *, source: str, note: str | None = None) -> Fact[str]:
        """Construct the canonical UNKNOWN fact — never guess instead of this."""
        return Fact[str](value=UNKNOWN, source=source, confidence=0.0, verified=False, note=note)

    @property
    def is_unknown(self) -> bool:
        return self.value == UNKNOWN and not self.verified


class SkillFact(BaseModel):
    """A skill/competency claim, categorized and evidence-graded.

    `evidence_level` must be HAS, DEMONSTRATED, or ADJACENT — see
    `EvidenceLevel` docstring for why MISSING/UNKNOWN are rejected here.
    ADJACENT skills are matching-only: rules.yaml's truth_validation marks
    ADJACENT as `internal_only` — they must never be surfaced as a claimed
    skill in a generated resume or answer.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    category: str
    evidence_level: EvidenceLevel
    source: str
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool
    note: str | None = None

    @field_validator("evidence_level")
    @classmethod
    def _must_be_storable(cls, v: EvidenceLevel) -> EvidenceLevel:
        if v not in STORABLE_EVIDENCE_LEVELS:
            raise ValueError(
                f"SkillFact.evidence_level={v!r} is a match-time-only classification "
                f"and cannot be stored in the candidate profile. Allowed: "
                f"{sorted(s.value for s in STORABLE_EVIDENCE_LEVELS)}"
            )
        return v


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    company: str
    start_date: str
    end_date: str
    domain: str | None = None
    location: str | None = None
    highlights: tuple[str, ...] = Field(default_factory=tuple)
    source: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    verified: bool = True


class ProjectEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    project_type: str
    stack: str | None = None
    highlights: tuple[str, ...] = Field(default_factory=tuple)
    source: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    verified: bool = True

    @property
    def is_professional_experience(self) -> bool:
        """Always False — self-initiated/academic projects, never work experience."""
        return False


class EducationEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    program: str
    institution: str
    graduation_date: str
    degree_level: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    verified: bool = True


class CertificationEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    provider: str | None = None
    covers: tuple[str, ...] = Field(default_factory=tuple)
    source: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    verified: bool = True


class AchievementEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    date: str | None = None
    highlights: tuple[str, ...] = Field(default_factory=tuple)
    source: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    verified: bool = True


class TargetRoles(BaseModel):
    model_config = ConfigDict(frozen=True)

    primary: tuple[str, ...] = Field(default_factory=tuple)
    secondary: tuple[str, ...] = Field(default_factory=tuple)
    exploratory: tuple[str, ...] = Field(default_factory=tuple)


class WorkPreferences(BaseModel):
    model_config = ConfigDict(frozen=True)

    remote: Fact[str]
    employment_types: tuple[str, ...] = Field(default_factory=tuple)
    willing_to_relocate: Fact[str]
    notice_period: Fact[str]


class LocationPreferences(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_location: Fact[str]
    preferred_locations: tuple[str, ...] = Field(default_factory=tuple)
    open_to_countries: Fact[str]


class SalaryPreferences(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: Fact[str]
    minimum_annual: Fact[str]
    target_annual: Fact[str]
    negotiable: Fact[str]


class VisaInformation(BaseModel):
    model_config = ConfigDict(frozen=True)

    nationality: Fact[str]
    requires_sponsorship_us: Fact[str]
    requires_sponsorship_uk: Fact[str]
    requires_sponsorship_eu: Fact[str]
    requires_sponsorship_other: Fact[str]
    currently_authorized_countries: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def is_fully_known(self) -> bool:
        return not any(
            f.is_unknown
            for f in (
                self.nationality,
                self.requires_sponsorship_us,
                self.requires_sponsorship_uk,
                self.requires_sponsorship_eu,
                self.requires_sponsorship_other,
            )
        )


class CandidateProfile(BaseModel):
    """The full canonical candidate knowledge base."""

    model_config = ConfigDict(frozen=True)

    identity_name: Fact[str]
    identity_current_location: Fact[str]

    contact_email: Fact[str]
    contact_phone: Fact[str]
    contact_linkedin: Fact[str]

    education: tuple[EducationEntry, ...] = Field(default_factory=tuple)
    certifications: tuple[CertificationEntry, ...] = Field(default_factory=tuple)
    experience: tuple[ExperienceEntry, ...] = Field(default_factory=tuple)
    projects: tuple[ProjectEntry, ...] = Field(default_factory=tuple)
    achievements: tuple[AchievementEntry, ...] = Field(default_factory=tuple)
    skills: tuple[SkillFact, ...] = Field(default_factory=tuple)

    # Spoken/written languages — distinct from programming languages, which
    # live under `skills` with category="technical". Resume did not state
    # any, so this stays empty rather than assuming e.g. English/Hindi.
    languages: tuple[Fact[str], ...] = Field(default_factory=tuple)

    target_roles: TargetRoles
    target_industries: tuple[str, ...] = Field(default_factory=tuple)
    excluded_roles: tuple[str, ...] = Field(default_factory=tuple)
    excluded_companies: tuple[str, ...] = Field(default_factory=tuple)

    work_preferences: WorkPreferences
    location_preferences: LocationPreferences
    salary_preferences: SalaryPreferences
    visa_information: VisaInformation

    parsed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_files: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def technical_skills(self) -> tuple[SkillFact, ...]:
        return tuple(s for s in self.skills if s.category == "technical")

    @property
    def soft_skills(self) -> tuple[SkillFact, ...]:
        return tuple(s for s in self.skills if s.category == "soft_skill")

    def get_skill(self, name: str) -> SkillFact | None:
        target = name.strip().lower()
        for s in self.skills:
            if s.name.strip().lower() == target:
                return s
        return None

    def skill_evidence(self, name: str) -> EvidenceLevel:
        """Classify a named skill against the profile for job matching.

        Returns HAS/DEMONSTRATED/ADJACENT when the skill is stored, or
        MISSING when the skill is genuinely absent from the profile. Never
        returns UNKNOWN here — an absent skill is a known negative
        (MISSING), not an unknown one. UNKNOWN is reserved for questions the
        profile has no basis to answer at all (e.g. visa status).
        """
        fact = self.get_skill(name)
        if fact is None:
            return EvidenceLevel.MISSING
        return fact.evidence_level

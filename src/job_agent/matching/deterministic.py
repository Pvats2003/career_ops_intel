"""Deterministic matching — BUILD PROMPT section 10's "deterministic
matching" half: exact/keyword skills, experience-years heuristics,
education, location, employment type, seniority, and eligibility/visa.

No LLM call happens anywhere in this module. Every score is explainable —
each function documents exactly what text pattern produced it — which is
what BUILD PROMPT's Definition of Done means by "decisions are explainable".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from job_agent.candidate.schema import CandidateProfile, EvidenceLevel
from job_agent.config.models import ProfileConfig
from job_agent.matching.text import (
    any_keyword_present,
    contains_keyword,
    extract_year_requirement,
    normalize,
)
from job_agent.matching.vocabulary import (
    COMMON_REQUIREMENT_KEYWORDS,
    DEGREE_REQUIRED_PATTERNS,
    JUNIOR_KEYWORDS,
    NO_SPONSORSHIP_PATTERNS,
    SENIOR_KEYWORDS,
)

_EVIDENCE_WEIGHT = {
    EvidenceLevel.DEMONSTRATED: 1.0,
    EvidenceLevel.HAS: 0.8,
    EvidenceLevel.ADJACENT: 0.4,
}

_NEUTRAL_SCORE = 55

_EVIDENCE_PRIORITY = {
    EvidenceLevel.MISSING: 0,
    EvidenceLevel.UNKNOWN: 0,
    EvidenceLevel.ADJACENT: 1,
    EvidenceLevel.HAS: 2,
    EvidenceLevel.DEMONSTRATED: 3,
}


def _find_evidence(profile: CandidateProfile, keyword: str) -> EvidenceLevel:
    """Fuzzy (substring) match a vocabulary keyword against stored skill
    names. Candidate skills are stored as authored ("Basic SQL", "Agile/
    Scrum", "Figma (basic)"), not as the bare vocabulary term ("SQL",
    "Agile", "Figma") — an exact-name match would wrongly report every one
    of these as MISSING, which is worse than a fuzzy match's occasional
    false positive on an unrelated skill sharing a short token."""
    kw = normalize(keyword)
    best = EvidenceLevel.MISSING
    for skill in profile.skills:
        name = normalize(skill.name)
        if kw and (kw in name or name in kw):
            if _EVIDENCE_PRIORITY[skill.evidence_level] > _EVIDENCE_PRIORITY[best]:
                best = skill.evidence_level
    return best


@dataclass
class JobText:
    """The subset of a Job's fields the deterministic matcher needs.

    Decoupled from the SQLAlchemy `Job` row / `jobs.schema.Job` on purpose —
    this module has no DB or job-source dependency, so it's trivially
    testable and reusable regardless of where a job came from.
    """

    title: str
    company: str
    description: str | None = None
    requirements: str | None = None
    preferred_qualifications: str | None = None
    location: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None

    @property
    def combined_text(self) -> str:
        return " \n".join(
            part
            for part in (
                self.title,
                self.description,
                self.requirements,
                self.preferred_qualifications,
            )
            if part
        )


@dataclass
class DeterministicMatch:
    skills_match: int
    experience_match: int
    role_match: int
    project_match: int
    education_match: int
    location_match: int
    seniority_match: int
    eligibility_match: int
    missing_requirements: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    hard_stop_reasons: list[str] = field(default_factory=list)
    excluded_reasons: list[str] = field(default_factory=list)


def _skills_and_projects(
    profile: CandidateProfile, job: JobText
) -> tuple[int, int, list[str]]:
    text = job.combined_text
    mentioned = any_keyword_present(text, COMMON_REQUIREMENT_KEYWORDS)
    if not mentioned:
        return _NEUTRAL_SCORE, _NEUTRAL_SCORE, []

    missing: list[str] = []
    skill_weighted_total = 0.0
    for keyword in mentioned:
        evidence = _find_evidence(profile, keyword)
        if evidence in _EVIDENCE_WEIGHT:
            skill_weighted_total += _EVIDENCE_WEIGHT[evidence]
        else:
            missing.append(keyword)
    skills_score = round(100 * skill_weighted_total / len(mentioned))

    project_text = " \n".join(
        f"{p.name} {p.stack or ''} {' '.join(p.highlights)}" for p in profile.projects
    )
    project_hits = [kw for kw in mentioned if contains_keyword(project_text, kw)]
    project_score = round(100 * len(project_hits) / len(mentioned)) if mentioned else _NEUTRAL_SCORE

    return skills_score, project_score, missing


def _role_alignment(profile_cfg: ProfileConfig, job: JobText) -> tuple[int, list[str]]:
    title = job.title
    for excluded in profile_cfg.excluded_roles:
        if contains_keyword(title, excluded):
            return 0, [f"excluded_role:{excluded}"]
    for excluded in profile_cfg.excluded_companies:
        if contains_keyword(job.company, excluded):
            return 0, [f"excluded_company:{excluded}"]

    for role in profile_cfg.target_roles.primary:
        if contains_keyword(title, role):
            return 90, []
    for role in profile_cfg.target_roles.secondary:
        if contains_keyword(title, role):
            return 72, []
    for role in profile_cfg.target_roles.exploratory:
        if contains_keyword(title, role):
            return 55, []
    return 35, []


def _education(profile: CandidateProfile, job: JobText) -> tuple[int, list[str], list[str]]:
    text = job.combined_text.lower()
    has_bachelors = any(e.degree_level.lower() == "bachelors" for e in profile.education)
    has_advanced = any(
        e.degree_level.lower() in {"masters", "mba", "phd"} for e in profile.education
    )

    for phrase, level in DEGREE_REQUIRED_PATTERNS:
        if phrase in text:
            if level == "bachelors" and has_bachelors:
                return 90, [], []
            if level in {"masters", "mba", "phd"} and not has_advanced:
                return 20, [f"job requires {level} degree, not present in candidate profile"], [
                    "required_degree_missing"
                ]
    return _NEUTRAL_SCORE, [], []


def _location(profile: CandidateProfile, job: JobText) -> tuple[int, list[str]]:
    if job.remote_type == "remote":
        return 88, []
    current = profile.location_preferences.current_location.value
    if job.location and current and current.split(",")[0].strip().lower() in job.location.lower():
        return 90, []
    if not job.location:
        return _NEUTRAL_SCORE, []
    if profile.location_preferences.open_to_countries.is_unknown:
        return 40, [
            "job location does not match candidate's current location and "
            "open_to_countries preference is UNKNOWN"
        ]
    return _NEUTRAL_SCORE, []


def _seniority(job: JobText) -> tuple[int, list[str], list[str]]:
    text = job.combined_text
    if any_keyword_present(text, JUNIOR_KEYWORDS):
        return 90, [], []
    senior_hits = any_keyword_present(job.title, SENIOR_KEYWORDS)
    if senior_hits:
        concern = f"title suggests senior-level ({', '.join(senior_hits)})"
        return 15, [concern], ["seniority_mismatch"]
    return _NEUTRAL_SCORE, [], []


def _experience(profile: CandidateProfile, job: JobText) -> tuple[int, list[str]]:
    required_years = extract_year_requirement(job.combined_text)
    available_years = _approx_years_of_experience(profile)
    if required_years is None:
        return _NEUTRAL_SCORE + 10, []
    if available_years >= required_years:
        return 85, []
    if required_years - available_years <= 1:
        return 55, [f"job asks for {required_years}+ years; candidate has ~{available_years:.1f}"]
    return 25, [f"job asks for {required_years}+ years; candidate has ~{available_years:.1f}"]


def _approx_years_of_experience(profile: CandidateProfile) -> float:
    total_months = 0.0
    today = date.today()
    for exp in profile.experience:
        start = _parse_year_month(exp.start_date)
        is_ongoing = exp.end_date.strip().lower() in {"present", "current"}
        end = today if is_ongoing else _parse_year_month(exp.end_date)
        if start is None or end is None:
            continue
        months = (end.year - start.year) * 12 + (end.month - start.month)
        total_months += max(0, months)
    return total_months / 12


def _parse_year_month(value: str) -> date | None:
    try:
        parts = value.strip().split("-")
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        return date(year, month, 1)
    except (ValueError, IndexError):
        return None


def _eligibility(profile: CandidateProfile, job: JobText) -> tuple[int, list[str], list[str]]:
    text = job.combined_text.lower()
    if any(phrase in text for phrase in NO_SPONSORSHIP_PATTERNS):
        if not profile.visa_information.is_fully_known:
            concern = (
                "job raises work-authorization/sponsorship requirements "
                "candidate hasn't confirmed"
            )
            return 30, [concern], ["unknown_work_authorization"]
        return 80, [], []
    return 80, [], []


def compute_deterministic_match(
    profile: CandidateProfile, profile_cfg: ProfileConfig, job: JobText
) -> DeterministicMatch:
    skills_score, project_score, missing = _skills_and_projects(profile, job)
    role_score, role_excluded = _role_alignment(profile_cfg, job)
    education_score, education_concerns, education_flags = _education(profile, job)
    location_score, location_concerns = _location(profile, job)
    seniority_score, seniority_concerns, seniority_flags = _seniority(job)
    experience_score, experience_concerns = _experience(profile, job)
    eligibility_score, eligibility_concerns, eligibility_flags = _eligibility(profile, job)

    return DeterministicMatch(
        skills_match=skills_score,
        experience_match=experience_score,
        role_match=role_score,
        project_match=project_score,
        education_match=education_score,
        location_match=location_score,
        seniority_match=seniority_score,
        eligibility_match=eligibility_score,
        missing_requirements=missing,
        concerns=[
            *education_concerns,
            *location_concerns,
            *seniority_concerns,
            *experience_concerns,
            *eligibility_concerns,
        ],
        hard_stop_reasons=[*education_flags, *seniority_flags, *eligibility_flags],
        excluded_reasons=role_excluded,
    )

"""Deterministic matching — BUILD PROMPT section 10's "deterministic
matching" half: exact/keyword skills, experience-years heuristics,
education, location, employment type, seniority, and eligibility/visa.

No LLM call happens anywhere in this module. Every score is explainable —
each function documents exactly what text pattern produced it — which is
what BUILD PROMPT's Definition of Done means by "decisions are explainable".

Matching Engine V2 (forensic false-positive audit — see the audit report
for full evidence): role alignment now goes through
`job_agent.matching.role_family`'s reusable 21-family classifier instead
of a closed exact-phrase list, and skills/project scoring goes through
`job_agent.matching.requirements`'s tiered coverage model instead of
"any keyword that happened to appear, weighted equally". Both changes are
about NOT letting a thin posting's incidental generic-keyword overlap
(e.g. "Python"/"API" in a GN&C engineering job) or an unrecognized
engineering title read as a strong or unknown-but-safe match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from job_agent.candidate.schema import CandidateProfile
from job_agent.config.models import ProfileConfig
from job_agent.matching.requirements import (
    NEUTRAL_SCORE as _NEUTRAL_SCORE,
)
from job_agent.matching.requirements import (
    detect_requirements,
    score_project_relevance,
    score_skills,
)
from job_agent.matching.role_family import (
    ADJACENT_CLUSTER,
    RoleFamily,
    candidate_role_families,
    classify_role_family,
)
from job_agent.matching.text import any_keyword_present, contains_keyword, extract_year_requirement
from job_agent.matching.vocabulary import (
    DEGREE_REQUIRED_PATTERNS,
    EXPLICIT_SENIORITY_MARKERS,
    FUNCTIONAL_MANAGER_SENIOR_TITLES,
    JUNIOR_KEYWORDS,
    NO_SPONSORSHIP_PATTERNS,
)

_ROLE_TIER_SCORE = {"primary": 90, "secondary": 72, "exploratory": 55}
_ADJACENT_UNCONFIRMED_ROLE_SCORE = 40
_DISTANT_FAMILY_ROLE_SCORE = 15
_UNKNOWN_FAMILY_ROLE_SCORE = 45

# Audit item F: an explicit years-required figure this far beyond the
# candidate's actual experience is a hard stop ("materially beyond"), not
# just a score penalty — distinct from an ordinary 1-2 year gap, which
# stays a penalty only (see _experience below).
_MATERIAL_EXPERIENCE_GAP_MIN_REQUIRED_YEARS = 5
_MATERIAL_EXPERIENCE_GAP_MAX_AVAILABLE_YEARS = 1.0


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
    # Only Arbeitnow currently supplies this as a verified per-listing fact
    # ("Visa sponsorship offered (per source posting)" / "No visa
    # sponsorship (per source posting)") — every other source leaves it
    # unset, and it must stay genuinely unset (never inferred) in that
    # case. See job_agent.jobs.sources.arbeitnow and `_eligibility` below.
    visa_information: str | None = None

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
    # Matching Engine V2 additions — audit items C/G/H. `risk_flags` are
    # STRONG NEGATIVE SIGNALS distinct from hard_stop_reasons: they drive
    # the score cap in job_agent.matching.scoring (so a risky job can
    # never display as an apparently excellent numeric match) without
    # forcing HUMAN_REQUIRED the way a real hard stop does — "an
    # incompatible role family" is deliberately never a hard stop per the
    # audit's explicit instruction, only ever a capped, flagged risk.
    risk_flags: list[str] = field(default_factory=list)
    # How many of the job's detected requirement keywords were BOTH
    # specific-tier (rare/domain-indicative, not generic) AND actually
    # matched by the candidate — the deterministic-only APPLY confidence
    # gate in job_agent.matching.decision reads this directly, so a
    # generic-overlap-only "match" can never unlock APPLY no matter how
    # high its numeric score.
    specific_matched_count: int = 0
    # Names of the requirement keywords the candidate actually matched —
    # audit item L (explainability): "explain WHICH skills and WHY they
    # matter", not just a percentage. Consumed by job_agent.matching.
    # scoring to build the reasoning text; not persisted as its own DB
    # column (the reasoning text it feeds into already is).
    matched_requirements: list[str] = field(default_factory=list)


def _role_alignment(
    profile: CandidateProfile, profile_cfg: ProfileConfig, job: JobText
) -> tuple[int, list[str], list[str], list[str]]:
    """Returns (score, excluded_reasons, concerns, risk_flags).

    Manual exact-phrase overrides (`excluded_roles`/`excluded_companies`)
    are checked FIRST and still work exactly as before — a candidate who
    explicitly names a role or company to skip should never have that
    silently reinterpreted by the family classifier. Everything else goes
    through `job_agent.matching.role_family`'s reusable classifier rather
    than the old closed two-item exact-phrase list."""
    title = job.title
    for excluded in profile_cfg.excluded_roles:
        if contains_keyword(title, excluded):
            return 0, [f"excluded_role:{excluded}"], [], []
    for excluded in profile_cfg.excluded_companies:
        if contains_keyword(job.company, excluded):
            return 0, [f"excluded_company:{excluded}"], [], []

    match = classify_role_family(title, job.combined_text)
    family = match.family
    candidate_tiers = candidate_role_families(profile, profile_cfg)

    if family in candidate_tiers:
        tier = candidate_tiers[family]
        return _ROLE_TIER_SCORE[tier], [], [], []

    if family == RoleFamily.OTHER_UNKNOWN:
        return (
            _UNKNOWN_FAMILY_ROLE_SCORE,
            [],
            ["role family could not be confidently classified from the posting"],
            [],
        )

    if family in ADJACENT_CLUSTER:
        return (
            _ADJACENT_UNCONFIRMED_ROLE_SCORE,
            [],
            [f"role family '{family.value}' is plausibly adjacent but not an explicit target role"],
            [],
        )

    # A clearly distant family (engineering/trades/sales/healthcare/etc.
    # the candidate has no stated or evidenced direction toward) — a
    # strong negative signal, but per the audit's explicit instruction
    # NEVER a hard stop on its own (an engineering title alone must not
    # disqualify a job outright): it caps the final score instead (see
    # job_agent.matching.scoring._apply_risk_caps).
    return (
        _DISTANT_FAMILY_ROLE_SCORE,
        [],
        [
            f"role family '{family.value}' does not align with candidate's "
            "target roles/career direction"
        ],
        ["role_family_mismatch"],
    )


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
    """Matching Engine V3 calibration fix C: a bare "Manager" in the title
    (e.g. "Product Manager", this candidate's own primary target-role
    title) no longer triggers a seniority hard stop on its own —
    `EXPLICIT_SENIORITY_MARKERS` requires an unambiguous qualifier
    (Senior/Sr./Lead/Principal/Staff/Director/Head of/VP/Chief) instead.
    `FUNCTIONAL_MANAGER_SENIOR_TITLES` separately still catches compound
    "<Function> Manager" titles (Engineering Manager, Marketing Manager,
    ...) that genuinely do signal managerial seniority even with no such
    qualifier — none of which is a title this candidate targets."""
    text = job.combined_text
    if any_keyword_present(text, JUNIOR_KEYWORDS):
        return 90, [], []
    senior_hits = any_keyword_present(job.title, EXPLICIT_SENIORITY_MARKERS) + any_keyword_present(
        job.title, FUNCTIONAL_MANAGER_SENIOR_TITLES
    )
    if senior_hits:
        concern = f"title suggests senior-level ({', '.join(senior_hits)})"
        return 15, [concern], ["seniority_mismatch"]
    return _NEUTRAL_SCORE, [], []


def _experience(profile: CandidateProfile, job: JobText) -> tuple[int, list[str], list[str]]:
    required_years = extract_year_requirement(job.combined_text)
    available_years = _approx_years_of_experience(profile)
    if required_years is None:
        # Matching Engine V2 fix (audit item E/16): a posting that never
        # states an explicit years figure is genuinely unknown, not
        # evidence the candidate is more likely to qualify — this used to
        # return _NEUTRAL_SCORE + 10, quietly rewarding missing
        # information as if it were a positive signal.
        return _NEUTRAL_SCORE, [], []
    if available_years >= required_years:
        return 85, [], []
    gap = required_years - available_years
    concern = f"job asks for {required_years}+ years; candidate has ~{available_years:.1f}"
    if gap <= 1:
        return 55, [concern], []
    hard_stops = []
    if (
        required_years >= _MATERIAL_EXPERIENCE_GAP_MIN_REQUIRED_YEARS
        and available_years < _MATERIAL_EXPERIENCE_GAP_MAX_AVAILABLE_YEARS
    ):
        # Audit item F: "explicit experience requirement materially beyond
        # candidate experience" — one of the enumerated legitimate hard
        # stops, distinct from an ordinary 1-2 year gap.
        hard_stops.append("experience_gap_material")
    return 25, [concern], hard_stops


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


def _eligibility(
    profile: CandidateProfile, job: JobText
) -> tuple[int, list[str], list[str], list[str]]:
    """Returns (score, concerns, hard_stop_reasons, risk_flags).

    Matching Engine V2 fix (audit item E/18): silence in a job posting is
    not evidence of eligibility either way. The old code defaulted to 80
    ("probably fine") for nearly every real posting, since almost none use
    one of a handful of exact no-sponsorship phrases — meaning a
    candidate's own genuinely UNKNOWN work-authorization status was
    effectively invisible to the scorer. Arbeitnow's real, verified
    per-listing sponsorship flag (the one source that can state this as
    fact rather than silence) is now actually consulted via
    `job.visa_information`, which the old code received but never used."""
    text = job.combined_text.lower()
    visa_info = (job.visa_information or "").lower()
    sponsorship_offered = "sponsorship offered" in visa_info
    sponsorship_denied = "no visa sponsorship" in visa_info or any(
        phrase in text for phrase in NO_SPONSORSHIP_PATTERNS
    )

    if sponsorship_offered:
        return 85, [], [], []
    if sponsorship_denied:
        if not profile.visa_information.is_fully_known:
            concern = (
                "job raises work-authorization/sponsorship requirements "
                "candidate hasn't confirmed"
            )
            return 30, [concern], ["unknown_work_authorization"], []
        return 80, [], [], []
    # No explicit signal in either direction: genuinely unknown. Do NOT
    # assume sponsorship is required merely because it's unmentioned, and
    # do NOT assume it's available merely because it's unmentioned either
    # — a conservative neutral score, flagged so the uncertainty stays
    # visible rather than silently defaulting to "probably fine".
    return _NEUTRAL_SCORE, [], [], ["eligibility_uncertain"]


def compute_deterministic_match(
    profile: CandidateProfile, profile_cfg: ProfileConfig, job: JobText
) -> DeterministicMatch:
    requirements = detect_requirements(job.combined_text)
    skills_result = score_skills(requirements, profile)
    project_result = score_project_relevance(requirements, profile)

    role_score, role_excluded, role_concerns, role_risk_flags = _role_alignment(
        profile, profile_cfg, job
    )
    education_score, education_concerns, education_flags = _education(profile, job)
    location_score, location_concerns = _location(profile, job)
    seniority_score, seniority_concerns, seniority_flags = _seniority(job)
    experience_score, experience_concerns, experience_flags = _experience(profile, job)
    eligibility_score, eligibility_concerns, eligibility_flags, eligibility_risk_flags = (
        _eligibility(profile, job)
    )

    return DeterministicMatch(
        skills_match=skills_result.score,
        experience_match=experience_score,
        role_match=role_score,
        project_match=project_result.score,
        education_match=education_score,
        location_match=location_score,
        seniority_match=seniority_score,
        eligibility_match=eligibility_score,
        missing_requirements=list(skills_result.missing),
        concerns=[
            *role_concerns,
            *education_concerns,
            *location_concerns,
            *seniority_concerns,
            *experience_concerns,
            *eligibility_concerns,
        ],
        hard_stop_reasons=[
            *education_flags, *seniority_flags, *experience_flags, *eligibility_flags,
        ],
        excluded_reasons=role_excluded,
        risk_flags=[*role_risk_flags, *eligibility_risk_flags],
        specific_matched_count=skills_result.specific_matched_count,
        matched_requirements=list(skills_result.matched),
    )

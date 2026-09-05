"""Skill/project coverage engine — Matching Engine V2 (audit items B/C/D).

Replaces the old assumption "a keyword appeared somewhere in the job text
== requirement evidence, and the fraction of THOSE keywords the candidate
happens to have == the skill score" with a coverage model that can't be
gamed by a thin posting that only mentions a couple of practically
universal terms:

- Every vocabulary term is tiered GENERIC (weight 1) or SPECIFIC (weight
  3) — see `job_agent.matching.vocabulary`. A job that only mentions
  generic terms can never alone justify a strong skill score (see
  `_GENERIC_ONLY_SKILL_CAP`).
- The coverage denominator is never allowed to shrink to fit whatever a
  sparse posting happened to say: if fewer than `_REQUIREMENT_FLOOR`
  distinct requirement keywords were found at all, the remainder is
  padded in as unmatched, specific-weight "unspecified requirement"
  slots — a real posting almost always asks for more than a thin
  Remotive/Arbeitnow listing spells out, and treating silence as "nothing
  else is required" is exactly the bug this replaces (audit item B: "if
  the source does not provide structured requirements, infer
  CONSERVATIVE requirement evidence from the job text").
- Project relevance counts ONLY specific-tier evidence — a project
  mentioning a generic term (Python, API, ...) contributes nothing to
  project relevance on its own (audit item D): meaningful alignment must
  be domain-specific, not incidental.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.candidate.schema import CandidateProfile, EvidenceLevel
from job_agent.matching.text import any_keyword_present, contains_keyword, fuzzy_overlap
from job_agent.matching.vocabulary import GENERIC_SKILL_KEYWORDS, SPECIFIC_SKILL_KEYWORDS

_EVIDENCE_WEIGHT = {
    EvidenceLevel.DEMONSTRATED: 1.0,
    EvidenceLevel.HAS: 0.8,
    EvidenceLevel.ADJACENT: 0.4,
}

_EVIDENCE_PRIORITY = {
    EvidenceLevel.MISSING: 0,
    EvidenceLevel.UNKNOWN: 0,
    EvidenceLevel.ADJACENT: 1,
    EvidenceLevel.HAS: 2,
    EvidenceLevel.DEMONSTRATED: 3,
}

NEUTRAL_SCORE = 55
_GENERIC_WEIGHT = 1
_SPECIFIC_WEIGHT = 3
_REQUIREMENT_FLOOR = 6
_GENERIC_ONLY_SKILL_CAP = 60
_NO_SPECIFIC_EVIDENCE_PROJECT_SCORE = 40


def _find_evidence(profile: CandidateProfile, keyword: str) -> EvidenceLevel:
    """Fuzzy (substring) match a vocabulary keyword against stored skill
    names — see the identical rationale this was originally written for
    in `job_agent.matching.deterministic`."""
    best = EvidenceLevel.MISSING
    for skill in profile.skills:
        if fuzzy_overlap(keyword, skill.name):
            if _EVIDENCE_PRIORITY[skill.evidence_level] > _EVIDENCE_PRIORITY[best]:
                best = skill.evidence_level
    return best


@dataclass(frozen=True)
class RequirementSet:
    """What the job text actually mentions, split by evidentiary tier."""

    generic: tuple[str, ...] = field(default_factory=tuple)
    specific: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_count(self) -> int:
        return len(self.generic) + len(self.specific)


@dataclass(frozen=True)
class SkillScoreResult:
    score: int
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    specific_matched_count: int


@dataclass(frozen=True)
class ProjectScoreResult:
    score: int
    matched: tuple[str, ...]


def detect_requirements(text: str) -> RequirementSet:
    """Which vocabulary terms (of either tier) the job text mentions at
    all — this is the "requirement evidence" the rest of this module
    scores against. Deliberately flat/cross-domain (not scoped to the
    job's classified role family): a Product Analyst posting can quite
    legitimately require Tableau, and scoping detection to one family's
    vocabulary would only produce false "not required" negatives."""
    generic = tuple(any_keyword_present(text, GENERIC_SKILL_KEYWORDS))
    specific = tuple(any_keyword_present(text, SPECIFIC_SKILL_KEYWORDS))
    return RequirementSet(generic=generic, specific=specific)


def _coverage(matched_weight: float, requirements: RequirementSet) -> float:
    total_mentioned_weight = (
        len(requirements.specific) * _SPECIFIC_WEIGHT + len(requirements.generic) * _GENERIC_WEIGHT
    )
    # Padding represents requirements a thin posting never spelled out at
    # all — real, but of genuinely UNKNOWN specificity, so it's weighted
    # like a generic term (1), not assumed to each be as damaging as a
    # confirmed specific one (3). This only ever engages when a posting
    # mentions fewer than `_REQUIREMENT_FLOOR` terms in total; the
    # audit's actual "many stated requirements, only 2 generic matched"
    # scenario (item C) already has enough real mentions that padding
    # never applies to it at all — this only softens thin-but-genuinely-
    # matched postings, never re-opens the bug padding exists to close.
    padding = max(0, _REQUIREMENT_FLOOR - requirements.total_count)
    total_weight = total_mentioned_weight + padding * _GENERIC_WEIGHT
    if total_weight <= 0:
        return 0.0
    return matched_weight / total_weight


def score_skills(requirements: RequirementSet, profile: CandidateProfile) -> SkillScoreResult:
    if requirements.total_count == 0:
        # No detectable requirement evidence either way — genuinely
        # neutral, not a signal of anything (see module docstring: this
        # is NOT the same case as "some evidence found, but thin/generic
        # only", which the coverage math below already handles).
        return SkillScoreResult(
            score=NEUTRAL_SCORE, matched=(), missing=(), specific_matched_count=0
        )

    matched: list[str] = []
    missing: list[str] = []
    matched_weight = 0.0
    specific_matched_count = 0

    for keyword in requirements.specific:
        evidence = _find_evidence(profile, keyword)
        if evidence in _EVIDENCE_WEIGHT:
            matched_weight += _EVIDENCE_WEIGHT[evidence] * _SPECIFIC_WEIGHT
            matched.append(keyword)
            specific_matched_count += 1
        else:
            missing.append(keyword)
    for keyword in requirements.generic:
        evidence = _find_evidence(profile, keyword)
        if evidence in _EVIDENCE_WEIGHT:
            matched_weight += _EVIDENCE_WEIGHT[evidence] * _GENERIC_WEIGHT
            matched.append(keyword)
        else:
            missing.append(keyword)

    score = round(100 * _coverage(matched_weight, requirements))
    if specific_matched_count == 0:
        # Audit item B/C: generic overlap alone (Python, API, SQL,
        # cross-functional, communication, documentation...) must never
        # by itself read as a strong or complete skill fit.
        score = min(score, _GENERIC_ONLY_SKILL_CAP)

    return SkillScoreResult(
        score=score,
        matched=tuple(matched),
        missing=tuple(missing),
        specific_matched_count=specific_matched_count,
    )


def score_project_relevance(
    requirements: RequirementSet, profile: CandidateProfile
) -> ProjectScoreResult:
    """Project relevance counts SPECIFIC-tier requirement evidence only —
    a project mentioning "Python" contributes nothing here on its own
    (audit item D: a Python ANPR project must not manufacture project
    relevance for an aerospace controls role just because both happen to
    say "Python"). Real, meaningful overlap still requires the job to
    have asked for something rare/domain-specific, that a candidate
    project independently mentions."""
    if not requirements.specific:
        return ProjectScoreResult(score=_NO_SPECIFIC_EVIDENCE_PROJECT_SCORE, matched=())

    project_text = " \n".join(
        f"{p.name} {p.stack or ''} {' '.join(p.highlights)}" for p in profile.projects
    )
    matched = tuple(kw for kw in requirements.specific if contains_keyword(project_text, kw))

    specific_only = RequirementSet(generic=(), specific=requirements.specific)
    matched_weight = len(matched) * _SPECIFIC_WEIGHT
    score = round(100 * _coverage(matched_weight, specific_only))
    return ProjectScoreResult(score=score, matched=matched)

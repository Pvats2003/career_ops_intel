"""Cross-checks a parsed CandidateProfile against the raw resume text —
the hallucination/invention guard Phase 4 requires.

Two matching strategies, chosen per field by how it was authored:

* STRICT (the field's full text must appear, normalized, as a contiguous
  substring of the resume) for facts that are direct structural
  transcriptions: identity, contact details, experience title/company,
  project names, education institutions, certification names, and
  self-declared (`HAS`) skills (which `candidate/skills.md` documents as
  "self-declared in resume competencies/certs" — i.e. literal terms).

* FUZZY (a configurable fraction of the claim's significant words must
  each appear somewhere in the resume) for fields that are legitimately
  paraphrased summaries of real resume content: achievement entries
  (candidate/achievements.md rewrites some resume bullets into cleaner
  prose) and `DEMONSTRATED`-skill evidence notes (short human-written
  pointers like "sprint structure used in KYC App project", not resume
  quotes). Strict matching would flag truthful paraphrasing as
  fabrication; a word-overlap threshold still catches genuine invention
  (a fabricated employer/number/technology shares few or no words with
  the real resume) while tolerating rewording of real facts.

Nothing here calls an LLM — asking a model "is this true?" would reintroduce
the exact hallucination risk this module exists to catch (BUILD PROMPT
section 59: prefer deterministic code over LLM calls).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_agent.candidate.schema import CandidateProfile, EvidenceLevel

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "at", "by", "is", "are", "was", "were", "it", "this", "that", "as",
}

# Below this many significant words, per-word overlap is too noisy to mean
# anything (a 1-word claim either trivially matches or trivially doesn't).
_MIN_WORDS_FOR_FUZZY = 2
_FUZZY_OVERLAP_THRESHOLD = 0.6


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    detail: str


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _significant_words(text: str) -> list[str]:
    return [w for w in _normalize(text).split() if len(w) >= 3 and w not in _STOPWORDS]


def _strict_match(resume_norm: str, claim: str) -> bool:
    needle = _normalize(claim)
    return bool(needle) and needle in resume_norm


def _fuzzy_match(
    resume_norm: str, claim: str, *, threshold: float = _FUZZY_OVERLAP_THRESHOLD
) -> bool:
    words = _significant_words(claim)
    if len(words) < _MIN_WORDS_FOR_FUZZY:
        return _strict_match(resume_norm, claim)
    hits = sum(1 for w in words if w in resume_norm)
    return (hits / len(words)) >= threshold


def validate_profile_against_resume(
    profile: CandidateProfile, resume_text: str
) -> list[ValidationIssue]:
    """Returns every claim in `profile` that could not be traced back to
    `resume_text`. An empty list means every fact was verified."""
    resume_norm = _normalize(resume_text)
    issues: list[ValidationIssue] = []

    def check_strict(field: str, claim: str) -> None:
        if not _strict_match(resume_norm, claim):
            issues.append(ValidationIssue(field, f"'{claim}' not found in resume text"))

    def check_fuzzy(field: str, claim: str) -> None:
        if not _fuzzy_match(resume_norm, claim):
            issues.append(
                ValidationIssue(field, f"'{claim}' does not sufficiently overlap resume text")
            )

    check_strict("identity_name", profile.identity_name.value)
    check_strict("contact_email", profile.contact_email.value)
    check_strict("contact_phone", profile.contact_phone.value)

    for i, exp in enumerate(profile.experience):
        check_strict(f"experience[{i}].title", exp.title)
        check_strict(f"experience[{i}].company", exp.company)

    for i, proj in enumerate(profile.projects):
        check_strict(f"projects[{i}].name", proj.name)

    for i, edu in enumerate(profile.education):
        check_strict(f"education[{i}].institution", edu.institution)

    for i, cert in enumerate(profile.certifications):
        check_strict(f"certifications[{i}].name", cert.name)

    for i, ach in enumerate(profile.achievements):
        claim = f"{ach.title} {' '.join(ach.highlights)}".strip()
        check_fuzzy(f"achievements[{i}]", claim)

    for i, skill in enumerate(profile.skills):
        field = f"skills[{i}].{skill.name}"
        if skill.evidence_level == EvidenceLevel.HAS:
            check_strict(field, skill.name)
        elif skill.evidence_level == EvidenceLevel.DEMONSTRATED:
            if not skill.note:
                issues.append(
                    ValidationIssue(
                        field, "DEMONSTRATED skill has no evidence note to verify against"
                    )
                )
            else:
                check_fuzzy(field, skill.note)
        # ADJACENT/MISSING/UNKNOWN are never claimed facts (rules.yaml marks
        # ADJACENT internal-only) — nothing to verify against the resume.

    return issues

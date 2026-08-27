"""Fabrication check for LLM-drafted application answers.

This is the inverse problem from `job_agent.resume.validator` (which
checks that a *structured claim* appears in the resume). Here we have
free-generated prose and need to catch invention *within* it — so instead
of checking one known field against the resume, we extract everything in
the draft that *looks like* a specific, checkable claim (a proper-noun-like
phrase, or a multi-digit number that could be a fabricated metric) and
require each one to appear somewhere in the candidate's known facts or the
raw resume text. An answer that only uses generic, unremarkable language
naturally has nothing to flag; an answer that invents a named employer, a
specific technology, or a percentage/statistic gets caught precisely
because that's what makes it check-able at all.

Deterministic — no LLM call — matching this codebase's rule of never using
one model to check another's work when a plain check will do (asking an
LLM "is this true?" reintroduces the exact hallucination risk this module
guards against).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_agent.candidate.schema import CandidateProfile
from job_agent.matching.text import normalize

# 2+ consecutive capitalized words — catches invented employers, schools,
# products, technologies ("Morgan Stanley", "Google Cloud Platform") while
# leaving ordinary sentence-initial capitals alone (those aren't followed
# by another capitalized word). The negative lookahead stops a sentence-
# initial function word ("At Wayne Enterprises") from being glued onto the
# start of the real proper-noun phrase.
_LEADING_FUNCTION_WORDS = (
    "At|The|I|In|On|For|With|My|This|That|We|You|They|He|She|It|A|An|As|By|To"
)
_PROPER_NOUN_PATTERN = re.compile(
    rf"\b(?!(?:{_LEADING_FUNCTION_WORDS})\s)(?:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b"
)
# 2+ digit numbers — catches invented metrics/statistics. Single digits are
# excluded: "led a team of 5" is too generic to usefully check either way.
_NUMBER_PATTERN = re.compile(r"\b\d{2,}\b")

_COMMON_PHRASES_ALLOWLIST = {
    "the company", "this role", "the team", "my experience", "the position",
}


@dataclass(frozen=True)
class AnswerValidationResult:
    passed: bool
    unverifiable_claims: tuple[str, ...]


def _known_facts_blob(profile: CandidateProfile, resume_text: str) -> str:
    parts = [resume_text]
    for exp in profile.experience:
        parts.append(f"{exp.title} {exp.company} {' '.join(exp.highlights)}")
    for proj in profile.projects:
        parts.append(f"{proj.name} {proj.stack or ''} {' '.join(proj.highlights)}")
    for edu in profile.education:
        parts.append(f"{edu.program} {edu.institution}")
    for cert in profile.certifications:
        parts.append(f"{cert.name} {cert.provider or ''}")
    for ach in profile.achievements:
        parts.append(f"{ach.title} {' '.join(ach.highlights)}")
    for skill in profile.skills:
        parts.append(skill.name)
    return normalize(" ".join(parts))


def validate_generated_answer(
    answer_text: str, profile: CandidateProfile, resume_text: str
) -> AnswerValidationResult:
    known = _known_facts_blob(profile, resume_text)
    unverifiable: list[str] = []

    for match in _PROPER_NOUN_PATTERN.findall(answer_text):
        if match.lower() in _COMMON_PHRASES_ALLOWLIST:
            continue
        if normalize(match) not in known:
            unverifiable.append(match)

    for match in _NUMBER_PATTERN.findall(answer_text):
        if not re.search(rf"\b{re.escape(match)}\b", known):
            unverifiable.append(match)

    return AnswerValidationResult(
        passed=not unverifiable, unverifiable_claims=tuple(dict.fromkeys(unverifiable))
    )

"""Skill Gap Intelligence — CAREER OS FINAL GOD MODE Part 2.6.

Every number here comes from `JobMatch.missing_requirements` — the exact
gap list the deterministic/semantic matcher already computed per job
(`job_agent.matching`), never a second, separate keyword scan. "Appears
in 43% of your strongest matches" literally counts how many of the
candidate's strongest (already-decided APPLY/REVIEW) matches list that
skill as missing. "Opportunities unlocked" counts, among that same real
set, how many jobs would have ZERO remaining gaps if the candidate had
exactly this one skill — i.e. `missing_requirements == [skill]` — a
concrete, computable, honest definition, never a guessed uplift number.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.candidate.career_paths import CareerPathResult
from job_agent.db.models import JobMatch as JobMatchRow

_MIN_SAMPLE = 3
_STRONG_DECISIONS = frozenset({"APPLY", "REVIEW"})


@dataclass(frozen=True)
class SkillGapEntry:
    skill: str
    frequency_count: int
    frequency_pct: float
    unlocks_count: int
    relevant_career_paths: tuple[str, ...]


def discover_skill_gaps(
    matches: list[JobMatchRow],
    career_paths: list[CareerPathResult],
    *,
    top_n: int = 5,
    min_sample: int = _MIN_SAMPLE,
) -> list[SkillGapEntry]:
    """`matches` should already be filtered to the candidate's strongest
    matches (e.g. decision in APPLY/REVIEW) — this module doesn't filter
    by decision itself, so the caller stays in control of what "strongest"
    means. Returns `[]` (never a percentage from a tiny sample) below
    `min_sample`."""
    strong = [m for m in matches if m.decision in _STRONG_DECISIONS]
    if len(strong) < min_sample:
        return []

    frequency: dict[str, int] = {}
    for match in strong:
        for skill in match.missing_requirements or []:
            frequency[skill] = frequency.get(skill, 0) + 1

    unlocks: dict[str, int] = {
        skill: sum(
            1 for m in strong if list(m.missing_requirements or []) == [skill]
        )
        for skill in frequency
    }

    path_skills: dict[str, list[str]] = {}
    for path in career_paths:
        for skill in path.missing_skills:
            path_skills.setdefault(skill, []).append(path.label)

    entries = [
        SkillGapEntry(
            skill=skill,
            frequency_count=count,
            frequency_pct=round(100 * count / len(strong), 1),
            unlocks_count=unlocks.get(skill, 0),
            relevant_career_paths=tuple(path_skills.get(skill, ())),
        )
        for skill, count in frequency.items()
    ]
    entries.sort(key=lambda e: (-e.frequency_count, e.skill))
    return entries[:top_n]

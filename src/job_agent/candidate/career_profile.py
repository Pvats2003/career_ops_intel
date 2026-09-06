"""Career Profile — CAREER OS FINAL GOD MODE Part 2.4.

"What kind of career is this candidate building" derived ENTIRELY from
`job_agent.candidate.career_paths.discover_career_paths` (already-scored,
evidence-backed paths) and the candidate's own stated location
preferences — never a second, separate judgment about the candidate.
Updates automatically as the underlying profile/behavior changes, since
it's recomputed fresh on every call rather than stored.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.candidate.career_paths import CareerPathResult
from job_agent.candidate.schema import CandidateProfile

_CLOSE_FIT_MARGIN = 5  # a second path within this many points also leads the "primary direction"


@dataclass(frozen=True)
class CareerProfile:
    primary_direction: str | None
    strengths: tuple[str, ...]
    growing_area: str | None
    skill_gaps: tuple[str, ...]
    best_locations: tuple[str, ...]


def _best_locations(profile: CandidateProfile) -> tuple[str, ...]:
    if profile.location_preferences.preferred_locations:
        return tuple(profile.location_preferences.preferred_locations)
    current = profile.location_preferences.current_location
    if current.verified and not current.is_unknown:
        return (current.value,)
    return ()


def _ranked_by_frequency(pools: list[tuple[str, ...]], *, limit: int) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for pool in pools:
        for value in pool:
            counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts, key=lambda v: (-counts[v], v))
    return tuple(ranked[:limit])


def build_career_profile(
    profile: CandidateProfile,
    career_paths: list[CareerPathResult],
    *,
    max_strengths: int = 5,
    max_skill_gaps: int = 3,
    pool_top_n_paths: int = 3,
) -> CareerProfile:
    best_locations = _best_locations(profile)
    if not career_paths:
        return CareerProfile(
            primary_direction=None, strengths=(), growing_area=None, skill_gaps=(),
            best_locations=best_locations,
        )

    top = career_paths[0]
    primary_direction = top.label
    if len(career_paths) > 1 and career_paths[1].fit_score >= top.fit_score - _CLOSE_FIT_MARGIN:
        primary_direction = f"{top.label} / {career_paths[1].label}"

    pool = career_paths[:pool_top_n_paths]
    strengths = _ranked_by_frequency([p.relevant_skills for p in pool], limit=max_strengths)
    skill_gaps = _ranked_by_frequency([p.missing_skills for p in pool], limit=max_skill_gaps)

    emerging = next((p for p in career_paths if p.career_upside == "Emerging"), None)
    growing_area = emerging.label if emerging else None

    return CareerProfile(
        primary_direction=primary_direction, strengths=strengths, growing_area=growing_area,
        skill_gaps=skill_gaps, best_locations=best_locations,
    )

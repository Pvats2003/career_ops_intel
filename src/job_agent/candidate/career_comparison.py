"""Career Path Comparison — CAREER OS FINAL GOD MODE Part 2.5.

Compares the candidate's discovered career paths (`job_agent.candidate.
career_paths`) side by side using only real, already-available signals:
fit score (the path's own evidence-backed score), job volume (a raw count
of currently ACTIVE postings whose title actually matches the path — no
normalized-but-fake precision), career upside (the path's own tiered
signal), skill gap (bucketed from the path's own `missing_skills`), and —
only when there's enough real application history — the candidate's own
interview rate for that path. `interview_rate` is `None` ("Insufficient
data") below `_MIN_APPLICATIONS_FOR_INTERVIEW_RATE`, never a rate
computed from a statistically meaningless sample of one or two.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.candidate.career_paths import CareerPathResult
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow
from job_agent.matching.text import contains_keyword

_UPSIDE_SCORE: dict[str, int] = {"High": 90, "Medium": 60, "Emerging": 75}
_SKILL_GAP_PENALTY: dict[str, int] = {"Low": 0, "Medium": 30, "High": 60}
_MIN_APPLICATIONS_FOR_INTERVIEW_RATE = 3
_INTERVIEW_STAGES = frozenset({"INTERVIEW", "OFFER"})
_APPLIED_STAGES = frozenset({"APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED"})


@dataclass(frozen=True)
class CareerPathComparisonRow:
    label: str
    current_fit: int
    job_volume: int
    career_upside: str
    skill_gap: str
    interview_rate: float | None
    interview_sample_size: int
    overall: int


def _matches_path(job: JobRow, path: CareerPathResult) -> bool:
    return any(contains_keyword(job.title, title) for title in path.typical_titles)


def _skill_gap_label(path: CareerPathResult) -> str:
    gaps = len(path.missing_skills)
    if gaps == 0:
        return "Low"
    if gaps <= 2:
        return "Medium"
    return "High"


def compare_career_paths(
    career_paths: list[CareerPathResult],
    active_jobs: list[JobRow],
    applications_with_jobs: list[tuple[ApplicationRow, JobRow]],
) -> list[CareerPathComparisonRow]:
    if not career_paths:
        return []

    volumes = {
        path.label: sum(1 for job in active_jobs if _matches_path(job, path))
        for path in career_paths
    }
    max_volume = max(volumes.values()) if volumes else 0
    applied = [
        (app, job) for app, job in applications_with_jobs if app.pipeline_stage in _APPLIED_STAGES
    ]

    rows = []
    for path in career_paths:
        volume = volumes[path.label]
        volume_score = round(100 * volume / max_volume) if max_volume else 0
        upside_score = _UPSIDE_SCORE.get(path.career_upside, 50)
        skill_gap = _skill_gap_label(path)
        skill_gap_penalty = _SKILL_GAP_PENALTY[skill_gap]

        matching_apps = [app for app, job in applied if _matches_path(job, path)]
        interview_rate: float | None = None
        if len(matching_apps) >= _MIN_APPLICATIONS_FOR_INTERVIEW_RATE:
            interviewed = sum(1 for app in matching_apps if app.pipeline_stage in _INTERVIEW_STAGES)
            interview_rate = round(interviewed / len(matching_apps), 3)

        overall = round(
            0.5 * path.fit_score + 0.2 * volume_score + 0.2 * upside_score
            + 0.1 * (100 - skill_gap_penalty)
        )

        rows.append(
            CareerPathComparisonRow(
                label=path.label, current_fit=path.fit_score, job_volume=volume,
                career_upside=path.career_upside, skill_gap=skill_gap,
                interview_rate=interview_rate, interview_sample_size=len(matching_apps),
                overall=overall,
            )
        )
    rows.sort(key=lambda r: r.overall, reverse=True)
    return rows

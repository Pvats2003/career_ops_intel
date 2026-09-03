"""Learning system — Career OS Phase 12 section 21.

Finds patterns in what the candidate has actually done — which matched
jobs they shortlisted/saved/applied to vs which they left untouched —
broken down by real, already-stored `Job` attributes (`remote_type`,
`employment_type`). Every number here is a real count over real rows;
nothing is inferred or guessed. A pattern is only surfaced when there's
enough data to say something meaningful (`min_sample`) and the rate is
meaningfully above the candidate's own overall baseline — never a vague
or overconfident claim about a handful of jobs.

"Ignored" here specifically means "matched, but the candidate never
created an Application row for it (no save, no shortlist, nothing)" —
the one honest proxy this system has for disinterest, since there is no
separate "the candidate explicitly dismissed this" tracking yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow

# A candidate "engaged with" a job the moment it has ANY Application row —
# `get_or_create_application` is called the instant they save/shortlist/
# mark-applied anything, so pipeline_stage's mere existence (regardless of
# which stage) is the signal, not any one specific stage.
_APPLIED_STAGES = frozenset({"APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED"})

_DIMENSIONS: dict[str, Callable[[JobRow], str | None]] = {
    "remote_type": lambda job: job.remote_type,
    "employment_type": lambda job: job.employment_type,
}


@dataclass(frozen=True)
class CategoryInsight:
    category: str
    saved: int
    ignored: int
    applied: int
    save_rate: float
    explanation: str


def _insights_for_dimension(
    jobs_with_applications: list[tuple[JobRow, ApplicationRow | None]],
    *,
    dimension_label: str,
    value_fn: Callable[[JobRow], str | None],
    min_sample: int,
    notable_multiplier: float,
) -> list[CategoryInsight]:
    total = len(jobs_with_applications)
    if total == 0:
        return []
    overall_saved = sum(1 for _, app in jobs_with_applications if app is not None)
    baseline_rate = overall_saved / total if total else 0.0

    buckets: dict[str, list[tuple[JobRow, ApplicationRow | None]]] = {}
    for job, app in jobs_with_applications:
        value = value_fn(job)
        if value:
            buckets.setdefault(value, []).append((job, app))

    insights = []
    for value, rows in buckets.items():
        if len(rows) < min_sample:
            continue
        saved = sum(1 for _, app in rows if app is not None)
        applied = sum(
            1 for _, app in rows if app is not None and app.pipeline_stage in _APPLIED_STAGES
        )
        ignored = len(rows) - saved
        save_rate = saved / len(rows)

        if baseline_rate > 0 and save_rate >= baseline_rate * notable_multiplier and saved >= 2:
            explanation = (
                f"Career OS noticed that you frequently shortlist {dimension_label} \"{value}\" "
                f"roles — saved {saved} of {len(rows)} matches ({round(save_rate * 100)}%), "
                f"versus your overall save rate of {round(baseline_rate * 100)}%."
            )
        else:
            explanation = (
                f"{dimension_label.capitalize()} \"{value}\": saved {saved} of {len(rows)} "
                f"matches ({round(save_rate * 100)}%)."
            )

        insights.append(
            CategoryInsight(
                category=value, saved=saved, ignored=ignored, applied=applied,
                save_rate=round(save_rate, 3), explanation=explanation,
            )
        )
    insights.sort(key=lambda i: i.save_rate, reverse=True)
    return insights


def discover_insights(
    jobs_with_applications: list[tuple[JobRow, ApplicationRow | None]],
    *,
    min_sample: int = 3,
    notable_multiplier: float = 1.5,
) -> tuple[list[CategoryInsight], list[str]]:
    """(category_insights, summary_sentences). `summary_sentences` is just
    the explanations of the notable ("Career OS noticed...") insights,
    for a short top-line list; every insight (notable or not) is still
    returned in `category_insights` for a full breakdown view."""
    all_insights: list[CategoryInsight] = []
    for dimension_label, value_fn in _DIMENSIONS.items():
        all_insights.extend(
            _insights_for_dimension(
                jobs_with_applications,
                dimension_label=dimension_label.replace("_", " "),
                value_fn=value_fn,
                min_sample=min_sample,
                notable_multiplier=notable_multiplier,
            )
        )
    summary = [i.explanation for i in all_insights if i.explanation.startswith("Career OS noticed")]
    return all_insights, summary

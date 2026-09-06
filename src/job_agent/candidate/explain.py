"""Explainable AI — Career OS FINAL GOD MODE Part 7.21.

Turns a ranked job's `components` breakdown (`job_agent.matching.
ranking`) into a numbered list of reasons plus one named main weakness.
Every number here is the literal weighted contribution that produced the
rank score — never a retroactively-invented justification for "why this
is #1".
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.matching.ranking import RankedJob

_COMPONENT_LABELS: dict[str, str] = {
    "match": "Candidate fit with your profile",
    "freshness": "How recently this was posted",
    "career_value": "Career value, based on the matcher's own decision",
    "company_fit": "Company fit",
    "application_ease": "How easy this is to apply to",
    "behavioral_fit": "Fit with your past save/apply behavior",
}


@dataclass(frozen=True)
class WhyBreakdown:
    rank_score: float
    reasons: list[str]
    main_weakness: str | None


def explain_ranking(ranked: RankedJob) -> WhyBreakdown:
    ranked_components = sorted(ranked.components.items(), key=lambda kv: kv[1], reverse=True)
    reasons = [
        f"{_COMPONENT_LABELS.get(name, name)} contributes {value:.1f} points"
        for name, value in ranked_components
        if value != 0
    ]
    reasons.extend(ranked.why)

    if ranked.gaps:
        main_weakness = ranked.gaps[0]
    elif ranked_components:
        weakest_name, weakest_value = min(ranked_components, key=lambda kv: kv[1])
        label = _COMPONENT_LABELS.get(weakest_name, weakest_name)
        main_weakness = f"{label} is the smallest contributor ({weakest_value:.1f} points)"
    else:
        main_weakness = None

    return WhyBreakdown(rank_score=ranked.rank_score, reasons=reasons, main_weakness=main_weakness)

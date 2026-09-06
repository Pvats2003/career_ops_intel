"""Morning briefing — CAREER OS FINAL GOD MODE Part 1.3.

A genuinely useful daily summary composed ENTIRELY from data this system
has already computed elsewhere — ranked jobs (`job_agent.matching.
ranking`), follow-up recommendations (`job_agent.applications.
follow_up`), and whatever insight sentences the caller has on hand
(behavioral insights and/or skill-gap analysis). This module never talks
to the database or an LLM itself; it's pure composition/formatting, so
it's trivially testable and can never silently diverge from what Top 10 /
Follow-ups / Insights already show elsewhere in the product.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.applications.follow_up import FollowUpRecommendation
from job_agent.matching.ranking import RankedJob

# Mirrors the DecisionBadge tiers already used everywhere else in the
# product (APPLY/REVIEW/SAVE/SKIP/HUMAN_REQUIRED) — never a second,
# competing tiering scheme.
_EXCEPTIONAL_DECISIONS = frozenset({"APPLY"})
_STRONG_DECISIONS = frozenset({"REVIEW"})
_POSSIBLE_DECISIONS = frozenset({"SAVE"})


@dataclass(frozen=True)
class BriefingHighlight:
    job_id: int
    title: str
    company: str
    location: str | None
    rank_score: float
    freshness_status: str
    why: str | None


@dataclass(frozen=True)
class MorningBriefing:
    total_opportunities: int
    exceptional_count: int
    strong_count: int
    possible_count: int
    top_highlights: tuple[BriefingHighlight, ...]
    follow_up_summaries: tuple[str, ...]
    career_insight: str | None
    recommendation: str | None


def compose_morning_briefing(
    ranked_jobs: list[RankedJob],
    follow_ups: list[FollowUpRecommendation],
    *,
    insight_sentences: list[str] | None = None,
    top_career_path_label: str | None = None,
    top_n_highlights: int = 3,
    max_follow_ups: int = 5,
) -> MorningBriefing:
    def _by_tier(decisions: frozenset[str]) -> list[RankedJob]:
        return [r for r in ranked_jobs if r.match is not None and r.match.decision in decisions]

    exceptional = _by_tier(_EXCEPTIONAL_DECISIONS)
    strong = _by_tier(_STRONG_DECISIONS)
    possible = _by_tier(_POSSIBLE_DECISIONS)
    worth_attention = exceptional + strong + possible

    highlights = tuple(
        BriefingHighlight(
            job_id=r.job.id,
            title=r.job.title,
            company=r.job.company_name,
            location=r.job.location,
            rank_score=r.rank_score,
            freshness_status=r.job.freshness_status,
            why=r.why[0] if r.why else None,
        )
        for r in ranked_jobs[:top_n_highlights]
    )

    follow_up_summaries = tuple(
        f"{f.job.company_name} — {f.applied_days_ago} days since application"
        for f in follow_ups[:max_follow_ups]
    )

    career_insight = insight_sentences[0] if insight_sentences else None
    recommendation = (
        f"Prioritize {top_career_path_label} this week." if top_career_path_label else None
    )

    return MorningBriefing(
        total_opportunities=len(worth_attention),
        exceptional_count=len(exceptional),
        strong_count=len(strong),
        possible_count=len(possible),
        top_highlights=highlights,
        follow_up_summaries=follow_up_summaries,
        career_insight=career_insight,
        recommendation=recommendation,
    )

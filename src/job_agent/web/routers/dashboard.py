"""Section 10 — the one screen that should answer "what are the best jobs
I should apply to right now" within seconds. Pure read aggregation over
`jobs`/`job_matches`/`applications` and the current resume validation
status; triggers no scan/match itself (the dashboard's "Scan for jobs" /
"Re-run matching" actions call `job_agent.web.routers.jobs`'s endpoints).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select

from job_agent.applications.follow_up import compute_follow_up_recommendations
from job_agent.candidate.briefing import compose_morning_briefing
from job_agent.candidate.career_paths import discover_career_paths
from job_agent.candidate.learning import compute_learned_preferences, discover_insights
from job_agent.db.models import Application, Candidate, JobMatch
from job_agent.db.models import Job as JobRow
from job_agent.matching.ranking import rank_jobs
from job_agent.resume.repository import get_latest_version
from job_agent.web import job_view
from job_agent.web.deps import CandidateDep, ConfigDep, SessionDep
from job_agent.web.routers.jobs import _application_for, _job_out
from job_agent.web.schemas import (
    BriefingHighlightOut,
    DashboardSummaryOut,
    MorningBriefingOut,
    NewSinceLastVisitOut,
    RankedJobOut,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_APPLY_PRIORITY_DECISIONS = {"APPLY"}
# Matching Engine V2 (audit item J): a "qualified match" is a job that
# cleared the save_threshold and isn't excluded/hard-stopped into
# HUMAN_REQUIRED — NOT merely "a JobMatch row exists for it" (the old
# `job_matches` metric's actual meaning, which counted every scored job
# regardless of quality, including outright SKIPs).
_QUALIFIED_DECISIONS = {"APPLY", "REVIEW", "SAVE"}
_HIGH_CONFIDENCE_DECISIONS = {"APPLY", "REVIEW"}
_APPLIED_STAGES = {"APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED"}


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(
    session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> DashboardSummaryOut:
    _, candidate_id = candidate
    jobs = list(session.execute(select(JobRow)).scalars())
    applications = list(
        session.execute(
            select(Application).where(Application.candidate_id == candidate_id)
        ).scalars()
    )

    version = get_latest_version(session, candidate_id)

    # Production-audit finding: this used to call `_latest_match()` once
    # per job (one query per row in `jobs`, unbounded N+1) — on Neon each
    # extra round-trip is real network latency, not just SQLite's local
    # disk-cache overhead the test suite runs against. One batched query
    # via `latest_matches_by_job()` regardless of how many jobs exist.
    matches_by_job = job_view.latest_matches_by_job(
        session, [job.id for job in jobs], candidate_id
    )
    jobs_scored = 0
    qualified_matches = 0
    high_confidence_matches = 0
    apply_priority_count = 0
    # Matching Engine V2 (audit item I): only decisions worth a human's
    # attention are even candidates for Top Opportunities — a SKIP must
    # NEVER appear there, so it's excluded here rather than relying on
    # ranking alone to bury it.
    rankable_pairs: list[tuple[JobRow, JobMatch | None]] = []
    for job in jobs:
        match_row = matches_by_job.get(job.id)
        if match_row is not None:
            jobs_scored += 1
            if match_row.decision in _QUALIFIED_DECISIONS:
                qualified_matches += 1
            if match_row.decision in _HIGH_CONFIDENCE_DECISIONS:
                high_confidence_matches += 1
            if match_row.decision in _APPLY_PRIORITY_DECISIONS:
                apply_priority_count += 1
            if match_row.decision != "SKIP":
                rankable_pairs.append((job, match_row))

    # Reuses the exact same composite ranking `new_since_last_visit`/
    # `morning_briefing` already use (job_agent.matching.ranking.
    # rank_jobs) instead of the old raw overall_score sort — rank_jobs'
    # own decision-aware career_value weighting means a HUMAN_REQUIRED
    # job is naturally deprioritized under APPLY/REVIEW/SAVE, never
    # ranked above them just for having a higher raw number.
    preferences = compute_learned_preferences(
        job_view.matched_jobs_with_applications(session, candidate_id)
    )
    ranked = rank_jobs(
        rankable_pairs, config.automation.priority_weights, preferences=preferences, limit=10
    )
    top_out = [
        _job_out(r.job, r.match, _application_for(session, r.job.id, candidate_id)) for r in ranked
    ]

    shortlisted = sum(
        1 for a in applications if a.pipeline_stage in ("SHORTLISTED", *_APPLIED_STAGES)
    )
    applied = sum(1 for a in applications if a.pipeline_stage in _APPLIED_STAGES)
    interviewing = sum(1 for a in applications if a.pipeline_stage in ("INTERVIEW", "OFFER"))
    offers = sum(1 for a in applications if a.pipeline_stage == "OFFER")

    return DashboardSummaryOut(
        resume_parsed=True,
        resume_validation_status=version.validation_status if version else None,
        # Redefined per audit item J — see _QUALIFIED_DECISIONS above.
        # `jobs_scored` keeps the OLD meaning available under its own,
        # honestly-named field for any consumer that actually wants it.
        job_matches=qualified_matches,
        jobs_scored=jobs_scored,
        qualified_matches=qualified_matches,
        high_confidence_matches=high_confidence_matches,
        shortlisted=shortlisted,
        applied=applied,
        interviewing=interviewing,
        offers=offers,
        total_jobs_discovered=len(jobs),
        apply_priority_count=apply_priority_count,
        top_opportunities=top_out,
    )


@router.get("/new-since-last-visit", response_model=NewSinceLastVisitOut)
def new_since_last_visit(
    session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> NewSinceLastVisitOut:
    """FINAL GOD MODE Part 1.2 — jobs discovered strictly after the
    candidate's PREVIOUS dashboard visit (`Candidate.last_dashboard_view_at`
    as it stood before this call), ranked the same way as Top 10. This
    endpoint then advances `last_dashboard_view_at` to now and commits —
    a deliberate side effect on a GET, exactly like a "mark as read": the
    point is "what's new since I last looked", so calling it again
    immediately must NOT show the same jobs again (per spec: "avoid
    repeatedly showing the same jobs as new"). A candidate with no prior
    visit sees everything currently active as new, once."""
    _, candidate_id = candidate
    candidate_row = session.get(Candidate, candidate_id)
    previous_visit_at = candidate_row.last_dashboard_view_at if candidate_row else None

    # Filtered to ACTIVE at the SQL level (dashboard performance forensic
    # fix, round 2): `new_jobs` only ever feeds `rank_jobs()` below, which
    # has always discarded non-ACTIVE rows anyway (see its docstring) — no
    # output change, just fewer CLOSED/EXPIRED rows fetched and thrown away.
    query = select(JobRow).where(JobRow.lifecycle_status == "ACTIVE")
    if previous_visit_at is not None:
        query = query.where(JobRow.discovered_at > previous_visit_at)
    new_jobs = list(session.execute(query).scalars())

    # Production-audit finding (dashboard-loading forensic audit): this
    # used to call `_latest_match()`/`_application_for()` once per job in
    # `new_jobs` — on a first visit (no previous_visit_at) that's every
    # active job, an unbounded N+1 on each. Both batched into one query
    # each regardless of how many jobs are "new".
    matches_by_job = job_view.latest_matches_by_job(
        session, [job.id for job in new_jobs], candidate_id
    )
    pairs = [(job, matches_by_job.get(job.id)) for job in new_jobs]
    preferences = compute_learned_preferences(
        job_view.matched_jobs_with_applications(session, candidate_id)
    )
    ranked = rank_jobs(pairs, config.automation.priority_weights, preferences=preferences)

    applications_by_job = job_view.applications_by_job(
        session, [r.job.id for r in ranked], candidate_id
    )
    out = [
        RankedJobOut(
            job=_job_out(r.job, r.match, applications_by_job.get(r.job.id)),
            rank_score=r.rank_score, why=list(r.why), gaps=list(r.gaps),
            recommendation=r.recommendation,
        )
        for r in ranked
    ]

    if candidate_row is not None:
        candidate_row.last_dashboard_view_at = datetime.now(UTC)
        session.commit()

    return NewSinceLastVisitOut(previous_visit_at=previous_visit_at, jobs=out)


@router.get("/briefing", response_model=MorningBriefingOut)
def morning_briefing(
    session: SessionDep, candidate: CandidateDep, config: ConfigDep
) -> MorningBriefingOut:
    """FINAL GOD MODE Part 1.3 — a genuinely useful daily summary, built
    entirely from data Top 10 / Follow-ups / Insights / Career Paths
    already compute (`job_agent.candidate.briefing` only formats it, it
    never re-derives anything), so this can never silently disagree with
    what those other views show."""
    profile, candidate_id = candidate

    # Production-audit finding (dashboard-loading forensic audit): this
    # used to call `_latest_match()` once per row in the WHOLE `jobs`
    # table — an unbounded N+1, the single largest contributor (alongside
    # `dashboard_summary`) to the multi-minute dashboard-load hang at
    # production job counts. Batched into one query regardless of count.
    # Filtered to ACTIVE at the SQL level (round 2 of this fix): nothing
    # else in this function derives a count from `jobs` — it only ever
    # feeds `rank_jobs()`, which has always discarded non-ACTIVE rows
    # anyway (see its docstring), so this changes zero output, only how
    # many CLOSED/EXPIRED rows get fetched and immediately thrown away.
    jobs = list(
        session.execute(select(JobRow).where(JobRow.lifecycle_status == "ACTIVE")).scalars()
    )
    matches_by_job = job_view.latest_matches_by_job(
        session, [job.id for job in jobs], candidate_id
    )
    pairs = [(job, matches_by_job.get(job.id)) for job in jobs]
    jobs_with_applications = job_view.matched_jobs_with_applications(session, candidate_id)
    preferences = compute_learned_preferences(jobs_with_applications)
    ranked = rank_jobs(pairs, config.automation.priority_weights, preferences=preferences)

    applications = list(
        session.execute(
            select(Application).where(Application.candidate_id == candidate_id)
        ).scalars()
    )
    applications_with_jobs = []
    for application in applications:
        job = session.get(JobRow, application.job_id)
        if job is not None:
            applications_with_jobs.append((application, job))
    follow_ups = compute_follow_up_recommendations(applications_with_jobs)

    _, insight_summary = discover_insights(jobs_with_applications)
    career_paths = discover_career_paths(profile)
    top_career_path_label = career_paths[0].label if career_paths else None

    briefing = compose_morning_briefing(
        ranked, follow_ups,
        insight_sentences=insight_summary, top_career_path_label=top_career_path_label,
    )

    return MorningBriefingOut(
        total_opportunities=briefing.total_opportunities,
        exceptional_count=briefing.exceptional_count,
        strong_count=briefing.strong_count,
        possible_count=briefing.possible_count,
        top_highlights=[
            BriefingHighlightOut(
                job_id=h.job_id, title=h.title, company=h.company, location=h.location,
                rank_score=h.rank_score,
                freshness_label=job_view.FRESHNESS_LABELS.get(
                    h.freshness_status, h.freshness_status
                ),
                why=h.why,
            )
            for h in briefing.top_highlights
        ],
        follow_up_summaries=list(briefing.follow_up_summaries),
        career_insight=briefing.career_insight,
        recommendation=briefing.recommendation,
    )

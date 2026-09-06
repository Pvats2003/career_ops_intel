"""Career Path Comparison (job_agent.candidate.career_comparison) —
CAREER OS FINAL GOD MODE Part 2.5."""

from __future__ import annotations

from job_agent.candidate.career_comparison import compare_career_paths
from job_agent.candidate.career_paths import CareerPathResult
from job_agent.db.models import Application as ApplicationRow
from job_agent.db.models import Job as JobRow


def _path(**overrides) -> CareerPathResult:
    base = dict(
        label="Product Operations", fit_score=90, evidence=("e",),
        relevant_skills=(), relevant_experience=(), missing_skills=(),
        typical_titles=("Product Operations Analyst",), career_upside="High",
        recommended_priority="HIGH",
    )
    base.update(overrides)
    return CareerPathResult(**base)


def _job(**overrides) -> JobRow:
    base = dict(company_name="Acme", title="Product Operations Analyst", job_fingerprint="fp")
    base.update(overrides)
    return JobRow(**base)


def _app(job_id, **overrides) -> ApplicationRow:
    base = dict(job_id=job_id, candidate_id=1, status="SUBMITTED", pipeline_stage="APPLIED")
    base.update(overrides)
    return ApplicationRow(**base)


def test_empty_career_paths_yields_empty_comparison():
    assert compare_career_paths([], [], []) == []


def test_job_volume_counts_only_matching_active_jobs():
    paths = [_path(label="Product Operations", typical_titles=("Product Operations Analyst",))]
    jobs = [
        _job(job_fingerprint="a", title="Product Operations Analyst"),
        _job(job_fingerprint="b", title="Software Engineer"),
    ]
    rows = compare_career_paths(paths, jobs, [])
    assert rows[0].job_volume == 1


def test_skill_gap_bucketed_from_missing_skills_count():
    paths = [
        _path(label="Low", missing_skills=()),
        _path(label="Medium", missing_skills=("A", "B")),
        _path(label="High", missing_skills=("A", "B", "C")),
    ]
    rows = {r.label: r for r in compare_career_paths(paths, [], [])}
    assert rows["Low"].skill_gap == "Low"
    assert rows["Medium"].skill_gap == "Medium"
    assert rows["High"].skill_gap == "High"


def test_interview_rate_none_below_minimum_sample():
    paths = [_path()]
    jobs = [_job(job_fingerprint=str(i)) for i in range(2)]
    applications = [(_app(i, pipeline_stage="INTERVIEW"), jobs[i]) for i in range(2)]
    rows = compare_career_paths(paths, jobs, applications)
    assert rows[0].interview_rate is None


def test_interview_rate_computed_once_minimum_sample_reached():
    paths = [_path()]
    jobs = [_job(job_fingerprint=str(i)) for i in range(4)]
    stages = ["INTERVIEW", "INTERVIEW", "APPLIED", "REJECTED"]
    applications = [(_app(i, pipeline_stage=stages[i]), jobs[i]) for i in range(4)]
    rows = compare_career_paths(paths, jobs, applications)
    assert rows[0].interview_sample_size == 4
    assert rows[0].interview_rate == 0.5


def test_only_applied_stage_applications_count_never_saved_only():
    paths = [_path()]
    jobs = [_job(job_fingerprint=str(i)) for i in range(4)]
    applications = [(_app(i, pipeline_stage="SAVED"), jobs[i]) for i in range(4)]
    rows = compare_career_paths(paths, jobs, applications)
    assert rows[0].interview_sample_size == 0
    assert rows[0].interview_rate is None


def test_higher_fit_score_ranks_higher_overall():
    paths = [
        _path(label="Weak", fit_score=40, career_upside="Medium"),
        _path(label="Strong", fit_score=95, career_upside="High"),
    ]
    rows = compare_career_paths(paths, [], [])
    assert rows[0].label == "Strong"


def test_overall_score_within_bounds():
    paths = [_path(fit_score=100, career_upside="High", missing_skills=())]
    rows = compare_career_paths(paths, [_job()], [])
    assert 0 <= rows[0].overall <= 100

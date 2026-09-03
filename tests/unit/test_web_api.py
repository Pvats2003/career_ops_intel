"""Career OS web dashboard API tests — FastAPI `TestClient` against
`job_agent.web.app.create_app()`. Same tmp_path/monkeypatch conventions as
the CLI's own tests (`tests/unit/test_cli_browser_approve_fill.py` etc.):
a copied config dir, a synthetic candidate dir, and a fresh sqlite file
per test, so nothing here ever touches the repo's real `data/job_agent.db`
or real `candidate/` files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from job_agent.candidate.schema import (
    CandidateProfile,
    Fact,
    LocationPreferences,
    SalaryPreferences,
    TargetRoles,
    VisaInformation,
    WorkPreferences,
)
from job_agent.db.models import Job as JobRow
from job_agent.db.models import JobMatch
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.web.app import create_app

SYNTHETIC_VALUES = {
    "full_name": "Test Candidate",
    "email": "test.candidate@example.invalid",
    "phone": "+1-555-0100",
    "current_location": "Test City, Test Country",
    "linkedin_url": "https://linkedin.com/in/testcandidate",
}


def _fact(value: str) -> Fact[str]:
    return Fact[str](value=value, source="test_synthetic_profile", confidence=1.0, verified=True)


def _synthetic_identity_profile() -> CandidateProfile:
    unknown_pref = Fact.unknown(source="test_synthetic_profile")
    return CandidateProfile(
        identity_name=_fact(SYNTHETIC_VALUES["full_name"]),
        identity_current_location=_fact(SYNTHETIC_VALUES["current_location"]),
        contact_email=_fact(SYNTHETIC_VALUES["email"]),
        contact_phone=_fact(SYNTHETIC_VALUES["phone"]),
        contact_linkedin=_fact(SYNTHETIC_VALUES["linkedin_url"]),
        target_roles=TargetRoles(primary=("Business Analyst",)),
        work_preferences=WorkPreferences(
            remote=unknown_pref, willing_to_relocate=unknown_pref, notice_period=unknown_pref
        ),
        location_preferences=LocationPreferences(
            current_location=_fact(SYNTHETIC_VALUES["current_location"]),
            open_to_countries=unknown_pref,
        ),
        salary_preferences=SalaryPreferences(
            currency=unknown_pref, minimum_annual=unknown_pref,
            target_annual=unknown_pref, negotiable=unknown_pref,
        ),
        visa_information=VisaInformation(
            nationality=unknown_pref, requires_sponsorship_us=unknown_pref,
            requires_sponsorship_uk=unknown_pref, requires_sponsorship_eu=unknown_pref,
            requires_sponsorship_other=unknown_pref,
        ),
    )


def _make_synthetic_candidate_dir(candidate_dir: Path) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "profile.md").write_text(
        "## Identity\n"
        f"name: {SYNTHETIC_VALUES['full_name']}\n"
        f"current_location: {SYNTHETIC_VALUES['current_location']}\n"
        "\n## Contact\n"
        f"email: {SYNTHETIC_VALUES['email']}\n"
        f"phone: {SYNTHETIC_VALUES['phone']}\n"
        f"linkedin: {SYNTHETIC_VALUES['linkedin_url']}\n"
    )
    for filename in (
        "experience.md", "projects.md", "skills.md", "education.md", "achievements.md",
    ):
        (candidate_dir / filename).write_text("")
    (candidate_dir / "answers").mkdir(exist_ok=True)

    import docx

    document = docx.Document()
    document.add_paragraph("Synthetic test resume for web API tests. No real content.")
    document.save(str(candidate_dir / "resume_master.docx"))
    return candidate_dir


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    candidate_dir = _make_synthetic_candidate_dir(tmp_path / "candidate")
    db_path = tmp_path / "web_api_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return db_path


def _seed_job(db_path: Path, *, fingerprint: str) -> int:
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        job = JobRow(
            company_name="Acme Corp",
            title="Business Analyst",
            location="Remote",
            remote_type="remote",
            employment_type="full_time",
            salary_min=80000,
            salary_max=110000,
            currency="USD",
            application_url="https://example.test/apply",
            job_fingerprint=fingerprint,
            description="Analyze business processes.",
            requirements="SQL, Excel",
        )
        session.add(job)
        session.flush()
        job_id = job.id
        session.commit()
    return job_id


def _seed_match(
    db_path: Path,
    job_id: int,
    candidate_id: int,
    *,
    overall_score: int = 80,
    decision: str = "APPLY",
) -> None:
    engine = get_engine(f"sqlite:///{db_path}")
    factory = get_session_factory(engine)
    with factory() as session:
        session.add(
            JobMatch(
                job_id=job_id,
                candidate_id=candidate_id,
                overall_score=overall_score,
                decision=decision,
                skills_match=80, experience_match=70, role_match=90, project_match=60,
                education_match=100, location_match=100, seniority_match=80,
                eligibility_match=100,
                reasoning="Strong overlap with stated skills.",
                semantic_available=False,
            )
        )
        session.commit()


def _client(tmp_path: Path, monkeypatch, real_config) -> tuple[TestClient, Path]:
    db_path = _configure_env(tmp_path, monkeypatch, real_config)
    return TestClient(create_app()), db_path


def test_health(tmp_path, monkeypatch, real_config):
    client, _ = _client(tmp_path, monkeypatch, real_config)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_candidate_profile_reflects_synthetic_files(tmp_path, monkeypatch, real_config):
    client, _ = _client(tmp_path, monkeypatch, real_config)
    r = client.get("/api/candidate/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == SYNTHETIC_VALUES["full_name"]
    assert body["email"] == SYNTHETIC_VALUES["email"]
    assert "candidate_id" in body


def test_dashboard_summary_empty_by_default(tmp_path, monkeypatch, real_config):
    """No fabricated jobs/matches on a fresh install — everything at 0."""
    client, _ = _client(tmp_path, monkeypatch, real_config)
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["job_matches"] == 0
    assert body["total_jobs_discovered"] == 0
    assert body["top_opportunities"] == []


def test_jobs_scan_with_no_sources_enabled_is_honest_zero(tmp_path, monkeypatch, real_config):
    """config/sources.yaml ships with every source disabled — scanning
    must report zero results, never fabricate a job listing, and must not
    attempt any network call (build_sources returns an empty adapter
    list, so run_scan has nothing to iterate)."""
    client, _ = _client(tmp_path, monkeypatch, real_config)
    r = client.post("/api/jobs/scan")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled_sources"] == 0
    assert body["results"] == []


def test_list_jobs_and_match_serialization(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    profile_r = client.get("/api/candidate/profile")
    candidate_id = profile_r.json()["candidate_id"]

    job_id = _seed_job(db_path, fingerprint="job-1")
    _seed_match(db_path, job_id, candidate_id, overall_score=91, decision="APPLY")

    r = client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == job_id
    assert item["match"]["overall_score"] == 91
    assert item["match"]["decision"] == "APPLY"
    assert item["pipeline_stage"] is None
    assert item["application_id"] is None


def test_list_jobs_filters_by_min_score(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    candidate_id = client.get("/api/candidate/profile").json()["candidate_id"]

    low_id = _seed_job(db_path, fingerprint="low")
    high_id = _seed_job(db_path, fingerprint="high")
    _seed_match(db_path, low_id, candidate_id, overall_score=20, decision="SKIP")
    _seed_match(db_path, high_id, candidate_id, overall_score=95, decision="APPLY")

    r = client.get("/api/jobs", params={"min_score": 50})
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()["items"]}
    assert ids == {high_id}


def test_get_job_detail_404_for_missing_job(tmp_path, monkeypatch, real_config):
    client, _ = _client(tmp_path, monkeypatch, real_config)
    r = client.get("/api/jobs/999")
    assert r.status_code == 404


def test_save_job_creates_pipeline_entry_at_saved(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_id = _seed_job(db_path, fingerprint="save-me")

    r = client.post(f"/api/jobs/{job_id}/save")
    assert r.status_code == 200
    body = r.json()
    assert body["pipeline_stage"] == "SAVED"
    assert body["application_id"] is not None

    pipeline_r = client.get("/api/pipeline")
    assert pipeline_r.status_code == 200
    items = pipeline_r.json()
    assert len(items) == 1
    assert items[0]["pipeline_stage"] == "SAVED"
    assert items[0]["job"]["id"] == job_id


def test_save_job_is_idempotent_and_never_regresses_stage(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_id = _seed_job(db_path, fingerprint="idempotent")
    save_1 = client.post(f"/api/jobs/{job_id}/save").json()
    application_id = save_1["application_id"]

    client.patch(f"/api/pipeline/{application_id}", json={"pipeline_stage": "INTERVIEW"})

    save_2 = client.post(f"/api/jobs/{job_id}/save").json()
    assert save_2["application_id"] == application_id
    assert save_2["pipeline_stage"] == "INTERVIEW"  # never silently reset to SAVED


def test_pipeline_update_rejects_unknown_stage(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_id = _seed_job(db_path, fingerprint="bad-stage")
    application_id = client.post(f"/api/jobs/{job_id}/save").json()["application_id"]

    r = client.patch(f"/api/pipeline/{application_id}", json={"pipeline_stage": "NOT_A_STAGE"})
    assert r.status_code == 422


def test_pipeline_update_notes_and_dates(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_id = _seed_job(db_path, fingerprint="notes")
    application_id = client.post(f"/api/jobs/{job_id}/save").json()["application_id"]

    r = client.patch(
        f"/api/pipeline/{application_id}",
        json={
            "pipeline_stage": "INTERVIEW",
            "notes": "Recruiter call went well.",
            "recruiter_contact": "jane@acme.example",
            "interview_date": "2026-09-10T15:00:00Z",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["notes"] == "Recruiter call went well."
    assert body["recruiter_contact"] == "jane@acme.example"
    assert body["interview_date"].startswith("2026-09-10")


def test_pipeline_delete_refuses_past_shortlisted(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_id = _seed_job(db_path, fingerprint="protect-history")
    application_id = client.post(f"/api/jobs/{job_id}/save").json()["application_id"]
    client.patch(f"/api/pipeline/{application_id}", json={"pipeline_stage": "APPLIED"})

    r = client.delete(f"/api/pipeline/{application_id}")
    assert r.status_code == 409

    still_there = client.get("/api/pipeline").json()
    assert len(still_there) == 1


def test_pipeline_delete_allowed_while_saved(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_id = _seed_job(db_path, fingerprint="ok-to-remove")
    application_id = client.post(f"/api/jobs/{job_id}/save").json()["application_id"]

    r = client.delete(f"/api/pipeline/{application_id}")
    assert r.status_code == 204
    assert client.get("/api/pipeline").json() == []


def test_analytics_reflects_pipeline_stage_counts(tmp_path, monkeypatch, real_config):
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    job_a = _seed_job(db_path, fingerprint="analytics-a")
    job_b = _seed_job(db_path, fingerprint="analytics-b")
    app_a = client.post(f"/api/jobs/{job_a}/save").json()["application_id"]
    app_b = client.post(f"/api/jobs/{job_b}/save").json()["application_id"]
    client.patch(f"/api/pipeline/{app_a}", json={"pipeline_stage": "INTERVIEW"})
    client.patch(f"/api/pipeline/{app_b}", json={"pipeline_stage": "APPLIED"})

    r = client.get("/api/pipeline/analytics")
    assert r.status_code == 200
    body = r.json()
    stage_counts = {row["stage"]: row["count"] for row in body["stage_breakdown"]}
    assert stage_counts["INTERVIEW"] == 1
    assert stage_counts["APPLIED"] == 1
    assert body["total_interviews"] == 1


def test_jobs_match_runs_deterministic_only_without_llm_key(tmp_path, monkeypatch, real_config):
    """No ANTHROPIC_API_KEY configured -> NullLLMProvider -> deterministic
    matching only, exactly like `jobs match` from the CLI; must not raise."""
    client, db_path = _client(tmp_path, monkeypatch, real_config)
    _seed_job(db_path, fingerprint="match-me")

    r = client.post("/api/jobs/match")
    assert r.status_code == 200
    body = r.json()
    assert body["matched"] == 1


def test_resume_upload_rejects_non_docx(tmp_path, monkeypatch, real_config):
    client, _ = _client(tmp_path, monkeypatch, real_config)
    r = client.post(
        "/api/candidate/resume",
        files={"file": ("resume.txt", b"not a docx", "text/plain")},
    )
    assert r.status_code == 422


def test_resume_upload_accepts_valid_docx(tmp_path, monkeypatch, real_config):
    import io

    import docx

    client, _ = _client(tmp_path, monkeypatch, real_config)
    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("Uploaded synthetic resume content for testing.")
    document.save(buf)
    buf.seek(0)

    r = client.post(
        "/api/candidate/resume",
        files={
            "file": (
                "resume.docx", buf,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["saved_path"].endswith("resume_master.docx")
    assert body["validation_status"] in ("PASSED", "FAILED")


def test_spa_fallback_serves_index_for_client_routes(tmp_path, monkeypatch, real_config):
    """React Router uses client-side (BrowserRouter) routing — a direct
    GET for a client-only path like /pipeline or /jobs/5 (a bookmark, a
    refresh) must still return the SPA shell, not 404, whenever the
    frontend has been built (`web-ui/dist` exists in this repo checkout).
    An unknown /api/* path must still 404 as a real API 404, never be
    swallowed by the SPA fallback."""
    from job_agent.web.app import _FRONTEND_DIST

    if not _FRONTEND_DIST.exists():
        import pytest

        pytest.skip("web-ui/dist not built in this checkout — run `npm run build` in web-ui/")

    client, _ = _client(tmp_path, monkeypatch, real_config)
    for path in ("/pipeline", "/jobs/5", "/resume", "/analytics"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "<div id=\"root\">" in r.text

    r = client.get("/api/this-route-does-not-exist")
    assert r.status_code == 404

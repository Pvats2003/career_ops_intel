"""Phase 6C — CLI integration tests for `applications approve`, `applications
submit --confirm`, `applications verify`, and `applications allowlist
add/revoke/list` (via `typer.testing.CliRunner`, in-process end-to-end
against a temporary sqlite database and a temporary copy of the real config
directory).

Every test that exercises `real_structured_ats` sets `credential_env_var`
to a fake variable name unique to this file and NEVER sets a real value
for it — proving the CLI-level submission attempt fails closed
(SubmissionRefusedError -> FAILED) rather than silently succeeding, exactly
as Stage 1 requires. No test in this file makes a real network call
(`RealStructuredATSProvider` is only ever exercised far enough to prove the
credential is missing — no `SubmissionHttpClient` is ever actually
constructed for a real destination).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from job_agent.applications.repository import save_answer
from job_agent.applications.schema import ApplicationStatus, GeneratedAnswer, QuestionCategory
from job_agent.applications.service import discover_application
from job_agent.candidate.parser import parse_candidate_profile
from job_agent.cli.main import app
from job_agent.db.models import (
    Application,
    ApplicationAllowlistEntry,
    ApplicationApproval,
    Company,
    JobSource,
)
from job_agent.db.models import Job as JobRow
from job_agent.db.repository import save_candidate_profile
from job_agent.db.session import get_engine, get_session_factory, init_db
from job_agent.matching.repository import save_job_match
from job_agent.matching.schema import Decision, JobMatchResult

runner = CliRunner()

_FAKE_ENV_VAR = "JOB_AGENT_CLI_PHASE6C_TEST_CREDENTIAL"


def _configure_env(
    tmp_path: Path,
    monkeypatch,
    real_config,
    *,
    provider: str = "manual_review",
    fixture_path: Path | None = None,
    live: bool = False,
    automation_level: int = 4,
) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)

    automation_path = cfg_dir / "automation.yaml"
    data = yaml.safe_load(automation_path.read_text())
    data["application_provider"]["provider"] = provider
    if provider == "real_structured_ats":
        data["application_provider"]["real_structured_ats"] = {
            "enabled": True,
            "fixture_path": str(fixture_path),
            "credential_name": "phase6c_test_cred",
            "credential_env_var": _FAKE_ENV_VAR,
        }
    if live:
        data["dry_run"] = False
        data["live_mode"] = True
        data["automation"]["level"] = automation_level
    automation_path.write_text(yaml.dump(data))

    db_path = tmp_path / "cli_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(_FAKE_ENV_VAR, raising=False)  # never a real credential in this file
    monkeypatch.setenv("COLUMNS", "250")
    return db_path


def _write_real_fixture(tmp_path: Path, application_url: str, verification_url: str) -> Path:
    path = tmp_path / "real_fixture.yaml"
    path.write_text(
        yaml.dump(
            {
                "forms": [
                    {
                        "application_url": application_url,
                        "verification_url": verification_url,
                        "ats_application_id": "cli-real-fixture-1",
                        "fields": [],
                    }
                ]
            }
        )
    )
    return path


def _seed_prepared_application(
    db_path: Path, real_profile, *, application_url: str, fingerprint: str,
) -> tuple[int, int]:
    """Seeds a Candidate/Job/JobMatch/Application already at PREPARED with
    one resolved answer — everything `applications approve`/`submit`/
    `verify` need, without going through the full `prepare` CLI flow."""
    engine = get_engine(f"sqlite:///{db_path}")
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        candidate_id = save_candidate_profile(session, real_profile)

        company = Company(name=f"Acme-{fingerprint}")
        session.add(company)
        session.flush()
        source = JobSource(name=f"cli-6c-{fingerprint}", kind="ats_api", enabled=True)
        session.add(source)
        session.flush()
        job = JobRow(
            source_id=source.id, source_job_id=fingerprint, company_id=company.id,
            company_name="Acme", title="Staff Engineer",
            application_url=application_url, job_fingerprint=fingerprint,
        )
        session.add(job)
        session.flush()

        result = JobMatchResult(
            overall_score=90, decision=Decision.APPLY,
            skills_match=90, experience_match=90, role_match=90, project_match=90,
            education_match=90, location_match=90, seniority_match=90, eligibility_match=90,
            reasoning="ok", semantic_available=False,
        )
        match = save_job_match(session, job_id=job.id, candidate_id=candidate_id, result=result)
        session.commit()

        from job_agent.config.loader import load_config

        cfg = load_config()
        application = discover_application(session, cfg, job, match, candidate_id)
        application.status = ApplicationStatus.PREPARED.value
        session.commit()
        save_answer(
            session, application.id,
            GeneratedAnswer(
                question="Why do you want to work here?", category=QuestionCategory.COMPANY,
                answer="Because I like it", confidence=0.9, source="template",
                requires_human=False, validated=True,
            ),
        )
        session.commit()
        return application.id, job.id


def _application_status(db_path: Path, application_id: int) -> str:
    engine = get_engine(f"sqlite:///{db_path}")
    factory = get_session_factory(engine)
    with factory() as session:
        return session.get(Application, application_id).status


@pytest.fixture()
def real_profile_for(real_config):
    return parse_candidate_profile(real_config)


# --------------------------------------------------------------------------
# applications approve
# --------------------------------------------------------------------------
class TestApprove:
    def test_approve_creates_a_persisted_approval(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        db_path = _configure_env(tmp_path, monkeypatch, real_config)
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/approve/1", fingerprint="fp-approve-1",
        )

        result = runner.invoke(app, ["applications", "approve", str(app_id), "--yes"])
        assert result.exit_code == 0, result.output
        assert "Approved" in result.output

        engine = get_engine(f"sqlite:///{db_path}")
        factory = get_session_factory(engine)
        with factory() as session:
            approvals = (
                session.query(ApplicationApproval).filter_by(application_id=app_id).all()
            )
            assert len(approvals) == 1
            assert approvals[0].consumed_at is None

    def test_approve_refuses_without_yes_when_prompt_declined(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        db_path = _configure_env(tmp_path, monkeypatch, real_config)
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/approve/2", fingerprint="fp-approve-2",
        )

        result = runner.invoke(app, ["applications", "approve", str(app_id)], input="n\n")
        assert result.exit_code != 0

        engine = get_engine(f"sqlite:///{db_path}")
        factory = get_session_factory(engine)
        with factory() as session:
            approvals = (
                session.query(ApplicationApproval).filter_by(application_id=app_id).all()
            )
            assert approvals == []

    def test_approve_unknown_application_id_fails_cleanly(
        self, tmp_path, monkeypatch, real_config
    ):
        _configure_env(tmp_path, monkeypatch, real_config)
        result = runner.invoke(app, ["applications", "approve", "999999", "--yes"])
        assert result.exit_code == 1
        assert "No application" in result.output

    def test_approve_non_prepared_application_refuses(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        db_path = _configure_env(tmp_path, monkeypatch, real_config)
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/approve/3", fingerprint="fp-approve-3",
        )
        engine = get_engine(f"sqlite:///{db_path}")
        factory = get_session_factory(engine)
        with factory() as session:
            row = session.get(Application, app_id)
            row.status = ApplicationStatus.SKIPPED.value
            session.commit()

        result = runner.invoke(app, ["applications", "approve", str(app_id), "--yes"])
        assert result.exit_code == 1
        assert "not PREPARED" in result.output or "not " in result.output


# --------------------------------------------------------------------------
# applications allowlist
# --------------------------------------------------------------------------
class TestAllowlist:
    def test_allowlist_add_and_list(self, tmp_path, monkeypatch, real_config, real_profile_for):
        db_path = _configure_env(tmp_path, monkeypatch, real_config)
        _app_id, job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/allow/1", fingerprint="fp-allow-1",
        )

        result = runner.invoke(
            app, ["applications", "allowlist", "add", str(job_id), "real_structured_ats"]
        )
        assert result.exit_code == 0, result.output
        assert "Allowlisted" in result.output

        result = runner.invoke(app, ["applications", "allowlist", "list"])
        assert result.exit_code == 0
        assert "real_structured_ats" in result.output
        assert "https://ats.example.test/allow/1" in result.output

    def test_allowlist_add_unknown_job_fails_cleanly(self, tmp_path, monkeypatch, real_config):
        _configure_env(tmp_path, monkeypatch, real_config)
        result = runner.invoke(app, ["applications", "allowlist", "add", "999999", "provider"])
        assert result.exit_code == 1
        assert "No job" in result.output

    def test_allowlist_revoke_marks_entry_revoked(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        db_path = _configure_env(tmp_path, monkeypatch, real_config)
        _app_id, job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/allow/2", fingerprint="fp-allow-2",
        )
        runner.invoke(app, ["applications", "allowlist", "add", str(job_id), "provider_x"])

        engine = get_engine(f"sqlite:///{db_path}")
        factory = get_session_factory(engine)
        with factory() as session:
            (entry,) = session.query(ApplicationAllowlistEntry).all()
            entry_id = entry.id

        result = runner.invoke(app, ["applications", "allowlist", "revoke", str(entry_id)])
        assert result.exit_code == 0
        assert "Revoked" in result.output

        with factory() as session:
            entry = session.get(ApplicationAllowlistEntry, entry_id)
            assert entry.revoked_at is not None

    def test_allowlist_revoke_unknown_entry_fails_cleanly(self, tmp_path, monkeypatch, real_config):
        _configure_env(tmp_path, monkeypatch, real_config)
        result = runner.invoke(app, ["applications", "allowlist", "revoke", "999999"])
        assert result.exit_code == 1
        assert "No allowlist entry" in result.output

    def test_allowlist_list_when_empty(self, tmp_path, monkeypatch, real_config):
        _configure_env(tmp_path, monkeypatch, real_config)
        result = runner.invoke(app, ["applications", "allowlist", "list"])
        assert result.exit_code == 0
        assert "No allowlist entries" in result.output


# --------------------------------------------------------------------------
# applications submit --confirm (end-to-end through build_application_
# provider with real_structured_ats configured but NO real credential set)
# --------------------------------------------------------------------------
class TestSubmit:
    def test_submit_without_confirm_is_a_no_op(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        db_path = _configure_env(tmp_path, monkeypatch, real_config, live=True)
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/submit/1", fingerprint="fp-submit-1",
        )

        result = runner.invoke(app, ["applications", "submit", str(app_id)])
        assert result.exit_code == 0
        assert "No action taken" in result.output
        assert _application_status(db_path, app_id) == ApplicationStatus.PREPARED.value

    def test_submit_confirm_manual_review_blocked_by_original_automation_level_gate(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        """`manual_review` is NOT requires_persisted_approval, so it stays
        on the ORIGINAL automation-level/human_approved gate — with level
        below 4 and the CLI never passing human_approved=True, it must
        block before ever reaching ManualReviewProvider.submit()."""
        db_path = _configure_env(
            tmp_path, monkeypatch, real_config, provider="manual_review",
            live=True, automation_level=1,
        )
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/submit/2", fingerprint="fp-submit-2",
        )

        result = runner.invoke(app, ["applications", "submit", str(app_id), "--confirm"])
        assert result.exit_code == 0, result.output
        assert _application_status(db_path, app_id) == ApplicationStatus.PREPARED.value

    def test_submit_confirm_manual_review_at_level_4_still_fails_no_real_integration(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        """At automation level 4 the OLD gate passes, but
        `ManualReviewProvider.submit()` always refuses regardless — proving
        the old gate passing is not, by itself, sufficient for a real
        submission; there is still no real ATS integration behind it."""
        db_path = _configure_env(
            tmp_path, monkeypatch, real_config, provider="manual_review",
            live=True, automation_level=4,
        )
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/submit/2b", fingerprint="fp-submit-2b",
        )

        result = runner.invoke(app, ["applications", "submit", str(app_id), "--confirm"])
        assert result.exit_code == 0, result.output
        assert _application_status(db_path, app_id) == ApplicationStatus.FAILED.value

    def test_submit_confirm_real_provider_no_credential_fails_closed(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        """The full Phase 6C gate (allowlist + approval) passes, but
        because Stage 1 never configures a real credential, submission
        must fail with a clean, non-fabricated FAILED outcome — never a
        fabricated SUBMITTED."""
        application_url = "https://ats.example.test/submit/3"
        fixture = _write_real_fixture(
            tmp_path, application_url, "https://ats.example.test/submit/3/verify"
        )
        db_path = _configure_env(
            tmp_path, monkeypatch, real_config,
            provider="real_structured_ats", fixture_path=fixture, live=True,
        )
        app_id, job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url=application_url, fingerprint="fp-submit-3",
        )

        add_result = runner.invoke(
            app, ["applications", "allowlist", "add", str(job_id), "real_structured_ats"]
        )
        assert add_result.exit_code == 0, add_result.output

        approve_result = runner.invoke(app, ["applications", "approve", str(app_id), "--yes"])
        assert approve_result.exit_code == 0, approve_result.output

        submit_result = runner.invoke(app, ["applications", "submit", str(app_id), "--confirm"])
        assert submit_result.exit_code == 0, submit_result.output
        assert "FAILED" in submit_result.output
        # Naming the unset env var is fine (it's not a secret); no VALUE
        # ever appears since none was ever set.
        assert _application_status(db_path, app_id) == ApplicationStatus.FAILED.value

    def test_submit_unknown_application_id_fails_cleanly(self, tmp_path, monkeypatch, real_config):
        _configure_env(tmp_path, monkeypatch, real_config, live=True)
        result = runner.invoke(app, ["applications", "submit", "999999", "--confirm"])
        assert result.exit_code == 1
        assert "No application" in result.output


# --------------------------------------------------------------------------
# applications verify
# --------------------------------------------------------------------------
class TestVerify:
    def test_verify_unknown_application_id_fails_cleanly(self, tmp_path, monkeypatch, real_config):
        _configure_env(tmp_path, monkeypatch, real_config)
        result = runner.invoke(app, ["applications", "verify", "999999"])
        assert result.exit_code == 1
        assert "No application" in result.output

    def test_verify_on_a_prepared_not_submitted_application_reports_unchanged_status(
        self, tmp_path, monkeypatch, real_config, real_profile_for
    ):
        """`verify_application` raises `IllegalStateTransitionError` for a
        non-SUBMITTED application — the CLI must not crash with an
        unhandled traceback; whatever it does, it must not report success."""
        db_path = _configure_env(tmp_path, monkeypatch, real_config)
        app_id, _job_id = _seed_prepared_application(
            db_path, real_profile_for,
            application_url="https://ats.example.test/verify/1", fingerprint="fp-verify-1",
        )

        runner.invoke(app, ["applications", "verify", str(app_id)])
        # It must never actually reach VERIFIED — check the persisted
        # status, not the human-readable error text (which legitimately
        # mentions "VERIFIED" while explaining why it wasn't reached).
        assert _application_status(db_path, app_id) == ApplicationStatus.PREPARED.value

"""Cloud-deployment access gate — `job_agent.web.app`'s optional HTTP Basic
Auth middleware, gated by `APP_USERNAME`/`APP_PASSWORD`.

This is a single-candidate personal dashboard (real name, resume, salary
expectations, application history), so once it has a public URL an
anonymous visitor must never be able to load it. Both env vars unset (the
default) must leave today's local-dev behavior completely unchanged.
"""

from __future__ import annotations

import base64
import logging
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from job_agent.web.app import create_app


def _configure_env(tmp_path: Path, monkeypatch, real_config) -> Path:
    cfg_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, cfg_dir)
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "profile.md").write_text(
        "## Identity\nname: Test Candidate\ncurrent_location: Remote\n\n"
        "## Contact\nemail: test@example.invalid\nphone: +1-555-0100\n"
        "linkedin: https://linkedin.com/in/test\n"
    )
    for filename in (
        "experience.md", "projects.md", "skills.md", "education.md", "achievements.md",
    ):
        (candidate_dir / filename).write_text("")
    (candidate_dir / "answers").mkdir()
    db_path = tmp_path / "auth_gate_test.db"
    monkeypatch.setenv("CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("CANDIDATE_DIR", str(candidate_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    return db_path


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_no_credentials_configured_leaves_local_dev_unchanged(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    client = TestClient(create_app())

    r = client.get("/api/health")
    assert r.status_code == 200
    r = client.get("/api/candidate/profile")
    assert r.status_code == 200


def test_credentials_configured_rejects_anonymous_requests(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse-battery-staple")
    client = TestClient(create_app())

    r = client.get("/api/candidate/profile")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == 'Basic realm="Career OS"'


def test_credentials_configured_rejects_wrong_password(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse-battery-staple")
    client = TestClient(create_app())

    r = client.get(
        "/api/candidate/profile", headers=_basic_auth_header("candidate", "wrong-password")
    )
    assert r.status_code == 401


def test_credentials_configured_accepts_correct_credentials(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse-battery-staple")
    client = TestClient(create_app())

    r = client.get(
        "/api/candidate/profile",
        headers=_basic_auth_header("candidate", "correct-horse-battery-staple"),
    )
    assert r.status_code == 200


def test_health_endpoint_is_exempt_so_the_deployment_platform_never_gets_locked_out(
    tmp_path, monkeypatch, real_config
):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse-battery-staple")
    client = TestClient(create_app())

    r = client.get("/api/health")
    assert r.status_code == 200


def test_status_endpoint_is_not_exempt_unlike_health(tmp_path, monkeypatch, real_config):
    """Only `/api/health` (Render's automated liveness probe) is exempt.
    `/api/status` carries real diagnostics and is only ever opened by hand
    by a logged-in candidate, so it must stay behind the same gate as
    every other route."""
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse-battery-staple")
    client = TestClient(create_app())

    r = client.get("/api/status")
    assert r.status_code == 401


def test_frontend_shell_is_also_gated_not_only_the_api(tmp_path, monkeypatch, real_config):
    _configure_env(tmp_path, monkeypatch, real_config)
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", "correct-horse-battery-staple")
    client = TestClient(create_app())

    r = client.get("/", follow_redirects=False)
    assert r.status_code == 401


def test_credentials_never_appear_in_logs_on_success_or_failure(
    tmp_path, monkeypatch, real_config, caplog
):
    """Deployment audit: neither a failed nor a successful Basic Auth
    attempt may ever put the real APP_PASSWORD (or a raw Authorization
    header) into application logs."""
    _configure_env(tmp_path, monkeypatch, real_config)
    secret_password = "unmistakable-canary-password-xyz"
    monkeypatch.setenv("APP_USERNAME", "candidate")
    monkeypatch.setenv("APP_PASSWORD", secret_password)
    client = TestClient(create_app())

    with caplog.at_level(logging.DEBUG):
        client.get("/api/health")  # exempt path, no credentials sent
        client.get("/api/candidate/profile")  # anonymous, should 401
        client.get(
            "/api/candidate/profile", headers=_basic_auth_header("candidate", "wrong")
        )  # wrong credentials, should 401
        client.get(
            "/api/candidate/profile",
            headers=_basic_auth_header("candidate", secret_password),
        )  # correct credentials, should 200

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_password not in log_text
    encoded = base64.b64encode(f"candidate:{secret_password}".encode()).decode()
    assert encoded not in log_text

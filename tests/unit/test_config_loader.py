from __future__ import annotations

import pytest

from job_agent.config.loader import load_config


def test_load_config_succeeds(real_config):
    assert real_config.profile.target_roles.primary
    assert real_config.rules.safety.never_fabricate is True


def test_default_is_safe(real_config):
    """Default config must never allow submission out of the box."""
    assert real_config.dry_run is True
    assert real_config.live_mode is False
    assert real_config.is_submission_allowed() is False


def test_env_overrides_yaml_for_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("LIVE_MODE", "true")
    cfg = load_config()
    assert cfg.dry_run is False
    assert cfg.live_mode is True
    assert cfg.is_submission_allowed() is True


def test_submission_requires_both_switches(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("LIVE_MODE", "false")
    cfg = load_config()
    assert cfg.is_submission_allowed() is False

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("LIVE_MODE", "true")
    cfg = load_config()
    assert cfg.is_submission_allowed() is False


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(config_dir=tmp_path)


def test_unknown_yaml_key_rejected(tmp_path, real_config, monkeypatch):
    import shutil

    import yaml

    bad_dir = tmp_path / "config"
    shutil.copytree(real_config.env.config_dir, bad_dir)
    data = yaml.safe_load((bad_dir / "rules.yaml").read_text())
    data["totally_unexpected_key"] = True
    (bad_dir / "rules.yaml").write_text(yaml.dump(data))

    with pytest.raises(ValueError):
        load_config(config_dir=bad_dir)

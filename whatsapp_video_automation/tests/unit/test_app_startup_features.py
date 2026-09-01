"""Tests two app.py-level startup behaviors against a fully-wired real
`InstacoreSyncApp` (isolated tmp-path settings/data directories -- never
the real repo's config/ or the real LOCALAPPDATA):

- The first-run wizard's trigger/gating logic: shown once (until
  finished), skipped on subsequent launches, and only marked complete
  when the user actually finishes it (not on Cancel). `FirstRunWizard`
  itself is faked out so this never opens a real Qt dialog or does real
  network I/O.
- The automatic-backup gating logic: runs when none has ever run or the
  last one has aged out, skipped otherwise, and never raises out of
  startup even if the backup itself fails.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import instacore_sync.app as app_module
import instacore_sync.core.config as config_module


class _FakeWizard:
    """Stands in for the real FirstRunWizard: records whether
    apply_to_settings() was called, and exec() returns whatever the test
    configures, without ever showing a real modal dialog."""

    _next_exec_result: int = 0  # QDialog.DialogCode.Rejected, set per test

    def __init__(self, settings, signal_bus, pipeline_thread, app_icon) -> None:  # noqa: ANN001
        self.settings = settings
        self.apply_to_settings_called = False

    def exec(self) -> int:
        return type(self)._next_exec_result

    def apply_to_settings(self) -> None:
        self.apply_to_settings_called = True

    class DialogCode:
        Rejected = 0
        Accepted = 1


@pytest.fixture
def isolated_app(tmp_path: Path, monkeypatch) -> app_module.InstacoreSyncApp:
    settings_path = tmp_path / "config" / "settings.local.yaml"
    monkeypatch.setattr(config_module, "_default_settings_path", lambda: settings_path)
    monkeypatch.setattr(
        config_module,
        "_example_settings_path",
        lambda: Path(__file__).resolve().parents[2] / "config" / "settings.example.yaml",
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    return app_module.InstacoreSyncApp()


def test_wizard_shown_when_onboarding_not_complete(isolated_app, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "FirstRunWizard", _FakeWizard)
    _FakeWizard._next_exec_result = _FakeWizard.DialogCode.Rejected

    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)
    assert settings_repo.get("onboarding_complete") is None

    pipeline_thread = MagicMock()
    isolated_app._run_first_run_wizard(
        isolated_app.container, pipeline_thread, None, settings_repo
    )

    pipeline_thread.wait_until_ready.assert_called_once()
    # Rejected (Cancel) -> onboarding_complete must NOT be set, so it's
    # offered again next launch.
    assert settings_repo.get("onboarding_complete") is None


def test_wizard_accepted_applies_settings_and_marks_complete(isolated_app, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "FirstRunWizard", _FakeWizard)
    _FakeWizard._next_exec_result = _FakeWizard.DialogCode.Accepted

    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)
    pipeline_thread = MagicMock()

    isolated_app._run_first_run_wizard(
        isolated_app.container, pipeline_thread, None, settings_repo
    )

    assert settings_repo.get("onboarding_complete") == "true"


def test_run_skips_wizard_when_already_onboarded(isolated_app, monkeypatch, qt_app) -> None:
    """The gating check in .run() itself -- once onboarding_complete is
    set, FirstRunWizard must never even be constructed on a later launch."""
    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)
    settings_repo.set("onboarding_complete", "true")

    wizard_constructed = []
    monkeypatch.setattr(
        app_module,
        "FirstRunWizard",
        lambda *a, **kw: wizard_constructed.append(1) or _FakeWizard(*a, **kw),
    )

    pipeline_thread = isolated_app.container.resolve(app_module.PipelineThread)
    monkeypatch.setattr(pipeline_thread, "start", lambda: None)
    monkeypatch.setattr(pipeline_thread, "stop", lambda: None)
    monkeypatch.setattr(pipeline_thread, "request_stats_refresh", lambda: None)

    monkeypatch.setattr(app_module.MainWindow, "show", lambda self: None)
    monkeypatch.setattr(qt_app, "exec", lambda: 0, raising=False)

    isolated_app.run(qt_app)

    assert wizard_constructed == []


def test_automatic_backup_runs_when_none_recorded_yet(isolated_app) -> None:
    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)
    assert settings_repo.get("last_auto_backup_at") is None

    isolated_app._maybe_run_automatic_backup(settings_repo)

    recorded = settings_repo.get("last_auto_backup_at")
    assert recorded is not None
    from instacore_sync.services.backup.backup_service import list_backups

    assert len(list_backups(isolated_app.settings.backups_dir)) == 1


def test_automatic_backup_skipped_when_recent(isolated_app) -> None:
    from datetime import datetime

    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)
    settings_repo.set("last_auto_backup_at", datetime.now().isoformat())

    isolated_app._maybe_run_automatic_backup(settings_repo)

    from instacore_sync.services.backup.backup_service import list_backups

    assert list_backups(isolated_app.settings.backups_dir) == []


def test_automatic_backup_disabled_when_interval_is_zero(isolated_app) -> None:
    isolated_app.settings.app.auto_backup_interval_days = 0
    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)

    isolated_app._maybe_run_automatic_backup(settings_repo)

    assert settings_repo.get("last_auto_backup_at") is None


def test_automatic_backup_failure_is_swallowed_not_raised(isolated_app, monkeypatch) -> None:
    """A backup failure (disk full, permissions) must never look like an
    app crash -- this runs on every startup, unattended."""
    settings_repo = isolated_app.container.resolve(app_module.SettingsRepository)

    def _boom(paths):  # noqa: ANN001
        raise OSError("disk is full")

    monkeypatch.setattr(app_module, "create_backup", _boom)

    isolated_app._maybe_run_automatic_backup(settings_repo)  # must not raise

    assert settings_repo.get("last_auto_backup_at") is None

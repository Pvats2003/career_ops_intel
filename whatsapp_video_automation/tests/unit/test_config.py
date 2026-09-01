from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from instacore_sync.core.config import AppSettings, AppUiSettings, OcrSettings, UploadSettings


def test_settings_round_trip_through_yaml(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.local.yaml"
    monkeypatch.setattr("instacore_sync.core.config._default_settings_path", lambda: settings_path)
    monkeypatch.setattr("instacore_sync.core.config._example_settings_path", lambda: tmp_path / "missing.yaml")

    settings = AppSettings.load()
    settings.watch_folder = str(tmp_path / "watch")
    settings.ocr.min_confidence = 0.77
    settings.uploads.max_concurrent = 15
    settings.save()

    assert settings_path.exists()
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert raw["watch_folder"] == str(tmp_path / "watch")
    assert raw["ocr"]["min_confidence"] == 0.77
    assert raw["uploads"]["max_concurrent"] == 15

    reloaded = AppSettings.load()
    assert reloaded.ocr.min_confidence == 0.77
    assert reloaded.uploads.max_concurrent == 15


def test_default_ocr_engine_is_tesseract() -> None:
    from instacore_sync.domain.enums import OcrEngineName

    settings = AppSettings()
    assert settings.ocr.engine == OcrEngineName.TESSERACT


def test_processed_folders_default_under_user_data_dir() -> None:
    settings = AppSettings()
    assert "Processed" in settings.processed_folder
    assert "NeedsReview" in settings.needs_review_folder


def test_export_backup_then_load_backup_round_trips(tmp_path: Path) -> None:
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")
    settings.drive.root_folder_id = "drive-folder-123"
    settings.sheets.spreadsheet_id = "sheet-abc"
    settings.uploads.max_concurrent = 20

    backup_path = tmp_path / "backup.yaml"
    settings.export_backup(backup_path)

    loaded = AppSettings.load_backup(backup_path)
    assert loaded.watch_folder == str(tmp_path / "watch")
    assert loaded.drive.root_folder_id == "drive-folder-123"
    assert loaded.sheets.spreadsheet_id == "sheet-abc"
    assert loaded.uploads.max_concurrent == 20


def test_export_backup_never_writes_google_credentials(tmp_path: Path) -> None:
    settings = AppSettings()
    settings.drive.credentials_file = "config/credentials.json"  # a path, not a secret value itself

    backup_path = tmp_path / "backup.yaml"
    settings.export_backup(backup_path)

    content = backup_path.read_text(encoding="utf-8")
    assert "refresh_token" not in content
    assert "client_secret" not in content


def test_update_from_mutates_in_place_so_existing_references_see_it(tmp_path: Path) -> None:
    """Services hold a reference to the *same* AppSettings object app.py
    constructed them with — update_from must mutate fields on that object,
    not just return a new one the caller could forget to swap in."""
    live_settings = AppSettings()
    services_reference = live_settings  # simulates what a service constructor captured

    imported = AppSettings()
    imported.watch_folder = str(tmp_path / "new_watch")
    imported.uploads.max_concurrent = 30
    imported.ocr.min_confidence = 0.9

    live_settings.update_from(imported)

    assert services_reference.watch_folder == str(tmp_path / "new_watch")
    assert services_reference.uploads.max_concurrent == 30
    assert services_reference.ocr.min_confidence == 0.9
    assert services_reference is live_settings  # same object, not replaced


# -- frozen (PyInstaller-packaged) path resolution --------------------------------


def test_credentials_and_token_path_resolve_next_to_the_exe_when_frozen(tmp_path: Path, monkeypatch) -> None:
    """Regression test for a real packaging bug: the previous implementation
    resolved relative paths via `Path(__file__).resolve().parents[3]`,
    which only means anything for a source checkout — a module frozen into
    a PyInstaller bundle has no meaningful on-disk `__file__` to walk up
    from. Every one of the 500 installs this app ships as a Windows .exe
    needs `credentials.json`/`token.json`/`settings.local.yaml` resolved
    relative to the installed .exe's own directory instead."""
    import sys

    fake_exe = tmp_path / "InstaCoreSync" / "InstaCoreSync.exe"
    fake_exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    settings = AppSettings()
    settings.drive.credentials_file = "config/credentials.json"
    settings.drive.token_file = "config/token.json"

    assert settings.credentials_path == fake_exe.parent / "config" / "credentials.json"
    assert settings.token_path == fake_exe.parent / "config" / "token.json"


def test_credentials_path_still_resolves_against_source_tree_when_not_frozen(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    settings = AppSettings()
    settings.drive.credentials_file = "config/credentials.json"

    # Running from source, this must land inside the actual project's
    # config/ directory (not some arbitrary frozen-mode path), the same
    # place docs/GOOGLE_API_SETUP.md tells developers to put it.
    assert settings.credentials_path.name == "credentials.json"
    assert settings.credentials_path.parent.name == "config"
    assert (settings.credentials_path.parents[1] / "pyproject.toml").exists()


def test_absolute_credentials_path_is_never_rewritten_relative_to_app_dir(tmp_path: Path, monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "App.exe"))

    settings = AppSettings()
    absolute = tmp_path / "elsewhere" / "credentials.json"
    settings.drive.credentials_file = str(absolute)

    assert settings.credentials_path == absolute


def test_example_settings_path_uses_meipass_when_frozen(tmp_path: Path, monkeypatch) -> None:
    """The bundled settings.example.yaml seed template must be found via
    `sys._MEIPASS` (what PyInstaller actually sets, regardless of its
    internal onefile/onefolder layout) — not the app-base-dir used for
    user-writable files, which is a different location once frozen."""
    import sys

    from instacore_sync.core import config as config_module

    meipass_dir = tmp_path / "meipass_extracted"
    (meipass_dir / "config").mkdir(parents=True)
    (meipass_dir / "config" / "settings.example.yaml").write_text("watch_folder: ''\n")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "App.exe"))

    assert config_module._example_settings_path() == meipass_dir / "config" / "settings.example.yaml"


def test_max_concurrent_zero_is_rejected() -> None:
    """`max_concurrent=0` used to pass validation silently and make
    UploadWorkerPool spawn zero workers — every discovered video would
    queue forever with no error anywhere. Must be rejected up front."""
    with pytest.raises(ValidationError):
        UploadSettings(max_concurrent=0)


def test_jobs_retention_days_zero_or_negative_is_rejected() -> None:
    """A zero/negative retention window used to push the prune cutoff to
    today or the future, pruning jobs that had just completed instead of
    ones 30 days old — must be rejected up front."""
    with pytest.raises(ValidationError):
        AppUiSettings(jobs_retention_days=0)
    with pytest.raises(ValidationError):
        AppUiSettings(jobs_retention_days=-5)


def test_ocr_min_confidence_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OcrSettings(min_confidence=1.5)
    with pytest.raises(ValidationError):
        OcrSettings(min_confidence=-0.1)


def test_ocr_and_upload_non_positive_durations_are_rejected() -> None:
    with pytest.raises(ValidationError):
        OcrSettings(max_seconds_scanned=0)
    with pytest.raises(ValidationError):
        OcrSettings(frame_interval_seconds=0)
    with pytest.raises(ValidationError):
        UploadSettings(retry_backoff_seconds=0)
    with pytest.raises(ValidationError):
        AppUiSettings(poll_interval_seconds=0)

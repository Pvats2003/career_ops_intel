from __future__ import annotations

from pathlib import Path

import yaml

from instacore_sync.core.config import AppSettings


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

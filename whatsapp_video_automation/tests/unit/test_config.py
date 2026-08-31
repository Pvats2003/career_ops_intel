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

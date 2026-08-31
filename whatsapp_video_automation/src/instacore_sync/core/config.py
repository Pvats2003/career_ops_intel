"""Application configuration.

Settings are loaded from (in increasing priority):
  1. Built-in defaults below.
  2. `config/settings.local.yaml` (created from settings.example.yaml on first run).
  3. Environment variables prefixed `INSTACORE_` (e.g. `INSTACORE_OCR__ENGINE=paddleocr`).

The Settings view in the UI edits the same YAML file through `AppSettings.save()`,
so there is exactly one source of truth for persisted configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from instacore_sync.core.constants import (
    DEFAULT_DATA_DIR_NAME,
    DEFAULT_DB_FILENAME,
    DEFAULT_SETTINGS_FILENAME,
    DEVICE_ID_REGEX_DEFAULT,
)
from instacore_sync.domain.enums import OcrEngineName


def _repo_root() -> Path:
    # src/instacore_sync/core/config.py -> src/instacore_sync/core -> src/instacore_sync -> src -> project root
    return Path(__file__).resolve().parents[3]


def _default_settings_path() -> Path:
    return _repo_root() / "config" / DEFAULT_SETTINGS_FILENAME


def _example_settings_path() -> Path:
    return _repo_root() / "config" / "settings.example.yaml"


def user_data_dir() -> Path:
    """Per-user writable directory for the SQLite DB, logs, and OAuth tokens.

    Uses %LOCALAPPDATA% on Windows and falls back to ~/.local/share elsewhere
    so the app works during development on non-Windows machines too.
    """
    import os

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / DEFAULT_DATA_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


class DriveSettings(BaseModel):
    root_folder_id: str = ""
    shared_drive_id: str = ""
    date_folder_format: str = "%d %b"
    make_public_link: bool = True
    credentials_file: str = "config/credentials.json"
    token_file: str = "config/token.json"


class SheetColumns(BaseModel):
    date: str = "A"
    device_id: str = "B"
    filename: str = "C"
    drive_link: str = "D"
    status: str = "E"
    uploaded_at: str = "F"
    ocr_confidence: str = "G"


class SheetsSettings(BaseModel):
    spreadsheet_id: str = ""
    worksheet_name: str = "Uploads"
    columns: SheetColumns = Field(default_factory=SheetColumns)
    header_row: int = 1


class OcrSettings(BaseModel):
    engine: OcrEngineName = OcrEngineName.TESSERACT
    tesseract_cmd: str = ""
    min_confidence: float = 0.55
    max_seconds_scanned: float = 6.0
    frame_interval_seconds: float = 0.5
    device_id_pattern: str = DEVICE_ID_REGEX_DEFAULT
    full_scan_on_low_confidence: bool = True


class UploadSettings(BaseModel):
    max_concurrent: int = 12
    retry_count: int = 5
    retry_backoff_seconds: float = 2.0
    chunk_size_mb: int = 8
    duplicate_check: bool = True


class AppUiSettings(BaseModel):
    theme: str = "dark"
    auto_start_with_windows: bool = False
    notifications_enabled: bool = True
    minimize_to_tray: bool = True
    poll_interval_seconds: float = 2.0
    log_level: str = "INFO"
    # How long a COMPLETED/DUPLICATE job stays in the `jobs` working table
    # before being pruned on startup. The durable audit trail (`upload_logs`,
    # what the Logs screen searches/exports) is never touched — only the
    # live working table, which has no reason to keep growing forever across
    # months of 150-500 videos/day. FAILED and NEEDS_REVIEW rows are never
    # auto-pruned; they stay until a human resolves them.
    jobs_retention_days: int = 30


class _YamlSettingsSource(PydanticBaseSettingsSource):
    """Loads `config/settings.local.yaml` as a settings source.

    Seeds that file from `settings.example.yaml` on first run. Implemented
    as a `PydanticBaseSettingsSource` subclass (rather than a plain
    function) because pydantic-settings instantiates each source with
    `settings_cls` and then calls it with no further arguments.
    """

    def get_field_value(self, field, field_name: str) -> tuple[Any, str, bool]:  # noqa: ANN001
        # Unused: __call__ is overridden below to return the whole dict at
        # once instead of resolving one field at a time.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        path = _default_settings_path()
        if not path.exists():
            example = _example_settings_path()
            if example.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                return {}
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}


class AppSettings(BaseSettings):
    """Root settings object. Instantiate via `AppSettings.load()`."""

    model_config = SettingsConfigDict(
        env_prefix="INSTACORE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    watch_folder: str = ""
    processed_folder: str = str(user_data_dir() / "Processed")
    needs_review_folder: str = str(user_data_dir() / "NeedsReview")
    failed_folder: str = str(user_data_dir() / "Failed")

    drive: DriveSettings = Field(default_factory=DriveSettings)
    sheets: SheetsSettings = Field(default_factory=SheetsSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    uploads: UploadSettings = Field(default_factory=UploadSettings)
    app: AppUiSettings = Field(default_factory=AppUiSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSettingsSource(settings_cls),
            file_secret_settings,
        )

    @classmethod
    def load(cls) -> AppSettings:
        settings = cls()
        for folder in (settings.processed_folder, settings.needs_review_folder, settings.failed_folder):
            if folder:
                Path(folder).mkdir(parents=True, exist_ok=True)
        return settings

    def save(self) -> None:
        """Persist the current settings back to `config/settings.local.yaml`."""
        path = _default_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)

    def export_backup(self, destination: Path) -> None:
        """Write the current settings to an arbitrary file (Settings ->
        Export). Deliberately does **not** include `credentials.json` or
        the encrypted `token.json`/`token.key` — those are re-established
        by signing in again on whatever machine restores this backup,
        which is both simpler and avoids ever putting a copy of Drive/
        Sheets access next to a config file a user might casually email
        themselves or drop in a synced folder.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        with destination.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)

    @classmethod
    def load_backup(cls, source: Path) -> AppSettings:
        """Parse a backup file into a standalone `AppSettings` instance,
        without touching the live config file or the currently-running
        settings — the caller decides whether/how to apply it (see
        `update_from`)."""
        with source.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.model_validate(data)

    def update_from(self, other: AppSettings) -> None:
        """Copy every field from `other` onto `self` in place.

        Used to apply an imported backup to the settings object the running
        app already holds a reference to (services were constructed with
        *this* object, not a new one — replacing `self` wholesale wouldn't
        reach them).
        """
        for field_name in type(self).model_fields:
            setattr(self, field_name, getattr(other, field_name))

    @property
    def db_path(self) -> Path:
        return user_data_dir() / DEFAULT_DB_FILENAME

    @property
    def credentials_path(self) -> Path:
        p = Path(self.drive.credentials_file)
        return p if p.is_absolute() else _repo_root() / p

    @property
    def token_path(self) -> Path:
        p = Path(self.drive.token_file)
        return p if p.is_absolute() else _repo_root() / p

"""Unit tests for each Health Check page check — every check is tested in
isolation with fakes, since the whole point of this module is to
correctly classify a wide variety of failure modes into PASS/WARNING/
FAILED with an actionable suggested fix, not to actually hit Google APIs
in a test suite."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import DriveApiError, SheetsApiError
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import (
    GoogleAuthStatus,
    HealthStatus,
    OcrEngineStatus,
    WatcherStatus,
)
from instacore_sync.services.health import health_check_service as hcs


def test_check_internet_pass_and_fail() -> None:
    ok = hcs.check_internet(host="127.0.0.1", port=1)  # nothing listens on port 1 -> should fail fast
    assert ok.status == HealthStatus.FAILED
    assert ok.suggested_fix is not None


def test_check_internet_succeeds_against_a_real_local_listener() -> None:
    import socket

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        result = hcs.check_internet(host="127.0.0.1", port=port, timeout=1.0)
        assert result.status == HealthStatus.PASS
    finally:
        server.close()


def test_check_google_auth_authenticated() -> None:
    google_auth = MagicMock(status=GoogleAuthStatus.AUTHENTICATED, account_email="me@example.com")
    result = hcs.check_google_auth(google_auth)
    assert result.status == HealthStatus.PASS
    assert "me@example.com" in result.message


def test_check_google_auth_signed_out_is_warning_not_failure() -> None:
    """Not signed in yet is an onboarding state, not a failure -- a brand
    new install before the first-run wizard completes shouldn't show a
    scary red FAILED for something entirely expected."""
    google_auth = MagicMock(status=GoogleAuthStatus.SIGNED_OUT, account_email=None)
    result = hcs.check_google_auth(google_auth)
    assert result.status == HealthStatus.WARNING


def test_check_drive_skips_when_not_authenticated() -> None:
    result = hcs.check_drive(MagicMock(), "folder-123", GoogleAuthStatus.SIGNED_OUT)
    assert result.status == HealthStatus.WARNING
    assert "sign in" in result.message.lower()


def test_check_drive_fails_when_no_folder_configured() -> None:
    result = hcs.check_drive(MagicMock(), "", GoogleAuthStatus.AUTHENTICATED)
    assert result.status == HealthStatus.FAILED


def test_check_drive_passes_when_accessible() -> None:
    drive_client = MagicMock()
    drive_client.verify_root_folder_accessible.return_value = "My Videos"
    result = hcs.check_drive(drive_client, "folder-123", GoogleAuthStatus.AUTHENTICATED)
    assert result.status == HealthStatus.PASS
    assert "My Videos" in result.message


def test_check_drive_fails_on_api_error() -> None:
    drive_client = MagicMock()
    drive_client.verify_root_folder_accessible.side_effect = DriveApiError("not found")
    result = hcs.check_drive(drive_client, "folder-123", GoogleAuthStatus.AUTHENTICATED)
    assert result.status == HealthStatus.FAILED
    assert result.suggested_fix is not None


def test_check_sheets_warning_when_not_configured() -> None:
    """No spreadsheet is a legitimate, supported configuration (Sheets
    logging is optional) -- warn, don't fail."""
    result = hcs.check_sheets(MagicMock(), "", GoogleAuthStatus.AUTHENTICATED)
    assert result.status == HealthStatus.WARNING


def test_check_sheets_fails_on_api_error() -> None:
    sheets_client = MagicMock()
    sheets_client.verify_spreadsheet_accessible.side_effect = SheetsApiError("forbidden")
    result = hcs.check_sheets(sheets_client, "sheet-123", GoogleAuthStatus.AUTHENTICATED)
    assert result.status == HealthStatus.FAILED


def test_check_ocr_passes_when_any_engine_ready() -> None:
    ready_engine = MagicMock()
    ready_engine.name.value = "tesseract"
    ready_engine.status.return_value = OcrEngineStatus.READY
    factory = MagicMock()
    factory.engines_for.return_value = [ready_engine]
    result = hcs.check_ocr(factory)
    assert result.status == HealthStatus.PASS


def test_check_ocr_fails_when_no_engine_ready() -> None:
    dead_engine = MagicMock()
    dead_engine.name.value = "tesseract"
    dead_engine.status.return_value = OcrEngineStatus.UNAVAILABLE
    factory = MagicMock()
    factory.engines_for.return_value = [dead_engine]
    result = hcs.check_ocr(factory)
    assert result.status == HealthStatus.FAILED
    assert "Tesseract" in (result.suggested_fix or "")


def test_check_disk_space_pass_warning_fail_thresholds(monkeypatch, tmp_path: Path) -> None:
    import shutil as shutil_module

    def _usage(total_free: int):
        return lambda path: type("Usage", (), {"total": 0, "used": 0, "free": total_free})()

    monkeypatch.setattr(shutil_module, "disk_usage", _usage(10 * 1024**3))
    assert hcs.check_disk_space(tmp_path).status == HealthStatus.PASS

    monkeypatch.setattr(shutil_module, "disk_usage", _usage(1 * 1024**3))
    assert hcs.check_disk_space(tmp_path).status == HealthStatus.WARNING

    monkeypatch.setattr(shutil_module, "disk_usage", _usage(50 * 1024**2))
    assert hcs.check_disk_space(tmp_path).status == HealthStatus.FAILED


def test_check_folder_permissions_pass_when_all_writable(tmp_path: Path) -> None:
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")

    result = hcs.check_folder_permissions(settings)
    assert result.status == HealthStatus.PASS


def test_check_folder_permissions_fails_when_not_configured() -> None:
    settings = AppSettings()
    settings.watch_folder = ""
    settings.processed_folder = ""
    settings.needs_review_folder = ""
    settings.failed_folder = ""

    result = hcs.check_folder_permissions(settings)
    assert result.status == HealthStatus.FAILED


def test_check_database_connection_pass(database: Database) -> None:
    result = hcs.check_database_connection(JobsRepository(database))
    assert result.status == HealthStatus.PASS


def test_check_database_connection_fails_on_closed_db(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_migrated()
    db.close()
    # Force the thread-local connection to a definitely-closed one so the
    # next query raises, simulating a corrupted/inaccessible DB file.
    import sqlite3

    closed_conn = sqlite3.connect(":memory:")
    closed_conn.close()
    db._local.conn = closed_conn

    result = hcs.check_database_connection(JobsRepository(db))
    assert result.status == HealthStatus.FAILED


def test_check_watcher_statuses() -> None:
    assert hcs.check_watcher(WatcherStatus.RUNNING).status == HealthStatus.PASS
    assert hcs.check_watcher(WatcherStatus.STARTING).status == HealthStatus.WARNING
    assert hcs.check_watcher(WatcherStatus.ERROR).status == HealthStatus.FAILED
    assert hcs.check_watcher(WatcherStatus.STOPPED).status == HealthStatus.FAILED


def test_check_background_workers() -> None:
    assert hcs.check_background_workers(True, 3).status == HealthStatus.PASS
    assert hcs.check_background_workers(False, 0).status == HealthStatus.FAILED


def test_run_health_checks_returns_one_result_per_check_and_never_raises(
    tmp_path: Path, database: Database
) -> None:
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")

    google_auth = MagicMock(status=GoogleAuthStatus.SIGNED_OUT, account_email=None)
    drive_client = MagicMock()
    sheets_client = MagicMock()
    ocr_factory = MagicMock()
    ocr_factory.engines_for.return_value = []

    results = hcs.run_health_checks(
        settings=settings,
        jobs_repo=JobsRepository(database),
        google_auth=google_auth,
        drive_client=drive_client,
        sheets_client=sheets_client,
        ocr_engine_factory=ocr_factory,
        watcher_status=WatcherStatus.RUNNING,
        worker_pool_running=True,
        worker_pool_active_count=0,
    )

    assert len(results) == 10  # every check contributes exactly one result
    names = {r.name for r in results}
    assert "Internet" in names
    assert "Google Drive" in names
    assert "Database" in names


def test_run_health_checks_survives_a_check_raising_unexpectedly(
    tmp_path: Path, database: Database, monkeypatch
) -> None:
    """A bug in one check function must not blank the rest of the page."""
    settings = AppSettings()
    settings.watch_folder = str(tmp_path / "watch")
    settings.processed_folder = str(tmp_path / "Processed")
    settings.needs_review_folder = str(tmp_path / "NeedsReview")
    settings.failed_folder = str(tmp_path / "Failed")

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("unexpected bug in a check")

    monkeypatch.setattr(hcs, "check_internet", _boom)

    google_auth = MagicMock(status=GoogleAuthStatus.SIGNED_OUT, account_email=None)
    ocr_factory = MagicMock()
    ocr_factory.engines_for.return_value = []

    results = hcs.run_health_checks(
        settings=settings,
        jobs_repo=JobsRepository(database),
        google_auth=google_auth,
        drive_client=MagicMock(),
        sheets_client=MagicMock(),
        ocr_engine_factory=ocr_factory,
        watcher_status=WatcherStatus.RUNNING,
        worker_pool_running=True,
        worker_pool_active_count=0,
    )

    assert len(results) == 10  # still one entry per check, including the broken one
    assert any(r.status == HealthStatus.FAILED and "unexpectedly" in r.message for r in results)

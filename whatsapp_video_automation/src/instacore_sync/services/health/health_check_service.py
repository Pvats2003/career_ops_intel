"""Health Check page: a battery of read-only, side-effect-free checks a
non-technical user (or the person supporting them) can run to see, in
plain language, what's wrong and how to fix it — rather than having to
interpret a stack trace or guess why uploads aren't happening.

Every check function here is synchronous and potentially blocking
(network calls, disk I/O) — callers run this from a background thread
(see `PipelineOrchestrator.run_health_check`), never on the Qt UI thread.
Every check also independently catches its own failures: one check
raising must never prevent the rest of the page from rendering.
"""

from __future__ import annotations

import shutil
import socket
from pathlib import Path

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import DriveApiError, DriveAuthError, SheetsApiError
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import (
    GoogleAuthStatus,
    HealthStatus,
    OcrEngineStatus,
    WatcherStatus,
)
from instacore_sync.domain.models import HealthCheckResult
from instacore_sync.services.drive.drive_auth import GoogleAuthService
from instacore_sync.services.drive.drive_client import DriveClient
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.sheets.sheets_client import SheetsClient

_MIN_FREE_BYTES_WARN = 2 * 1024 * 1024 * 1024  # 2 GiB
_MIN_FREE_BYTES_FAIL = 200 * 1024 * 1024  # 200 MiB


def check_internet(host: str = "www.googleapis.com", port: int = 443, timeout: float = 3.0) -> HealthCheckResult:
    """A TCP+TLS-port-reachability check against the actual service this
    app talks to (not a generic "is the internet up" probe against some
    unrelated third party) — fast, and doesn't need `requests`/`aiohttp`
    as a dependency just for this one check."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return HealthCheckResult(name="Internet", status=HealthStatus.PASS, message="Connected")
    except OSError as exc:
        return HealthCheckResult(
            name="Internet",
            status=HealthStatus.FAILED,
            message=f"Could not reach {host}: {exc}",
            suggested_fix="Check your network connection. If you're behind a proxy or firewall, "
            "make sure it allows connections to Google APIs (googleapis.com, port 443).",
        )


def check_google_auth(google_auth: GoogleAuthService) -> HealthCheckResult:
    status = google_auth.status
    if status == GoogleAuthStatus.AUTHENTICATED:
        return HealthCheckResult(
            name="Google Authentication",
            status=HealthStatus.PASS,
            message=f"Signed in as {google_auth.account_email or 'your Google account'}",
        )
    if status in (GoogleAuthStatus.SIGNED_OUT, GoogleAuthStatus.EXPIRED):
        return HealthCheckResult(
            name="Google Authentication",
            status=HealthStatus.WARNING,
            message="Not signed in" if status == GoogleAuthStatus.SIGNED_OUT else "Sign-in expired",
            suggested_fix="Go to Settings -> Google Drive -> Sign in with Google.",
        )
    return HealthCheckResult(
        name="Google Authentication",
        status=HealthStatus.FAILED,
        message=f"Status: {status.value}",
        suggested_fix="Go to Settings -> Google Drive -> Sign in with Google.",
    )


def check_drive(
    drive_client: DriveClient, root_folder_id: str, auth_status: GoogleAuthStatus
) -> HealthCheckResult:
    if auth_status != GoogleAuthStatus.AUTHENTICATED:
        return HealthCheckResult(
            name="Google Drive",
            status=HealthStatus.WARNING,
            message="Skipped — sign in to Google first",
            suggested_fix="Go to Settings -> Google Drive -> Sign in with Google.",
        )
    if not root_folder_id:
        return HealthCheckResult(
            name="Google Drive",
            status=HealthStatus.FAILED,
            message="No root folder configured",
            suggested_fix="Go to Settings -> Google Drive and set a Root Folder ID.",
        )
    try:
        name = drive_client.verify_root_folder_accessible(root_folder_id)
        return HealthCheckResult(
            name="Google Drive", status=HealthStatus.PASS, message=f'Root folder "{name}" is accessible'
        )
    except (DriveApiError, DriveAuthError) as exc:
        return HealthCheckResult(
            name="Google Drive",
            status=HealthStatus.FAILED,
            message=str(exc),
            suggested_fix="Confirm the Root Folder ID in Settings is correct and that your Google "
            "account has access to it.",
        )


def check_sheets(
    sheets_client: SheetsClient, spreadsheet_id: str, auth_status: GoogleAuthStatus
) -> HealthCheckResult:
    if auth_status != GoogleAuthStatus.AUTHENTICATED:
        return HealthCheckResult(
            name="Google Sheets",
            status=HealthStatus.WARNING,
            message="Skipped — sign in to Google first",
            suggested_fix="Go to Settings -> Google Drive -> Sign in with Google.",
        )
    if not spreadsheet_id:
        return HealthCheckResult(
            name="Google Sheets",
            status=HealthStatus.WARNING,
            message="No spreadsheet configured — uploads will skip Sheets logging",
            suggested_fix="Go to Settings -> Google Sheets and set a Spreadsheet ID (optional).",
        )
    try:
        title = sheets_client.verify_spreadsheet_accessible(spreadsheet_id)
        return HealthCheckResult(
            name="Google Sheets", status=HealthStatus.PASS, message=f'Spreadsheet "{title}" is accessible'
        )
    except (SheetsApiError, DriveAuthError) as exc:
        return HealthCheckResult(
            name="Google Sheets",
            status=HealthStatus.FAILED,
            message=str(exc),
            suggested_fix="Confirm the Spreadsheet ID in Settings is correct and that your Google "
            "account has access to it.",
        )


def check_ocr(ocr_engine_factory: OcrEngineFactory) -> HealthCheckResult:
    engines = ocr_engine_factory.engines_for()
    statuses = [(e.name.value, e.status()) for e in engines]
    ready = [name for name, status in statuses if status == OcrEngineStatus.READY]
    if ready:
        return HealthCheckResult(
            name="OCR Engine", status=HealthStatus.PASS, message=f"Ready: {', '.join(ready)}"
        )
    detail = ", ".join(f"{name}: {status.value}" for name, status in statuses)
    return HealthCheckResult(
        name="OCR Engine",
        status=HealthStatus.FAILED,
        message=f"No OCR engine is ready ({detail})",
        suggested_fix="Install Tesseract OCR (https://github.com/UB-Mannheim/tesseract/wiki) and, if "
        "installed to a non-standard location, set its path in Settings -> OCR Engine.",
    )


def check_disk_space(path: Path) -> HealthCheckResult:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.anchor or Path.cwd())
    except OSError as exc:
        return HealthCheckResult(
            name="Disk Space",
            status=HealthStatus.FAILED,
            message=f"Could not check disk space for {path}: {exc}",
            suggested_fix="Confirm the folder's drive is connected and accessible.",
        )
    free_gb = usage.free / (1024**3)
    if usage.free < _MIN_FREE_BYTES_FAIL:
        return HealthCheckResult(
            name="Disk Space",
            status=HealthStatus.FAILED,
            message=f"Only {free_gb:.1f} GB free",
            suggested_fix="Free up disk space — videos can't be processed with almost no space left.",
        )
    if usage.free < _MIN_FREE_BYTES_WARN:
        return HealthCheckResult(
            name="Disk Space",
            status=HealthStatus.WARNING,
            message=f"{free_gb:.1f} GB free — getting low",
            suggested_fix="Consider freeing up disk space soon.",
        )
    return HealthCheckResult(name="Disk Space", status=HealthStatus.PASS, message=f"{free_gb:.1f} GB free")


def check_folder_permissions(settings: AppSettings) -> HealthCheckResult:
    import os

    folders = {
        "WhatsApp folder": settings.watch_folder,
        "Processed folder": settings.processed_folder,
        "Needs Review folder": settings.needs_review_folder,
        "Failed folder": settings.failed_folder,
    }
    problems = []
    for label, folder in folders.items():
        if not folder:
            problems.append(f"{label}: not configured")
            continue
        path = Path(folder)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            problems.append(f"{label}: can't create ({exc})")
            continue
        if not os.access(path, os.W_OK):
            problems.append(f"{label}: not writable ({path})")

    if not problems:
        return HealthCheckResult(
            name="Folder Permissions", status=HealthStatus.PASS, message="All folders are writable"
        )
    return HealthCheckResult(
        name="Folder Permissions",
        status=HealthStatus.FAILED,
        message="; ".join(problems),
        suggested_fix="Check the folder paths in Settings -> Folders, and that this Windows account "
        "has write access to each of them.",
    )


def check_database_connection(jobs_repo: JobsRepository) -> HealthCheckResult:
    try:
        jobs_repo.counts_by_status()
        return HealthCheckResult(name="Database", status=HealthStatus.PASS, message="Reachable")
    except Exception as exc:  # noqa: BLE001 - a health check must classify, not raise (covers RepositoryError)
        return HealthCheckResult(
            name="Database",
            status=HealthStatus.FAILED,
            message=str(exc),
            suggested_fix="Restart InstaCore Sync. If this keeps happening, see "
            "docs/RECOVERY_GUIDE.md — the database file may be corrupted.",
        )


def check_watcher(status: WatcherStatus) -> HealthCheckResult:
    if status == WatcherStatus.RUNNING:
        return HealthCheckResult(name="Folder Watcher", status=HealthStatus.PASS, message="Running")
    if status == WatcherStatus.STARTING:
        return HealthCheckResult(name="Folder Watcher", status=HealthStatus.WARNING, message="Starting up")
    return HealthCheckResult(
        name="Folder Watcher",
        status=HealthStatus.FAILED,
        message=f"Status: {status.value}",
        suggested_fix="Confirm the WhatsApp folder in Settings exists and is accessible, then restart.",
    )


def check_background_workers(worker_pool_running: bool, active_count: int) -> HealthCheckResult:
    if worker_pool_running:
        return HealthCheckResult(
            name="Background Workers",
            status=HealthStatus.PASS,
            message=f"Running ({active_count} uploading now)",
        )
    return HealthCheckResult(
        name="Background Workers",
        status=HealthStatus.FAILED,
        message="Not running",
        suggested_fix="Restart InstaCore Sync.",
    )


def run_health_checks(
    *,
    settings: AppSettings,
    jobs_repo: JobsRepository,
    google_auth: GoogleAuthService,
    drive_client: DriveClient,
    sheets_client: SheetsClient,
    ocr_engine_factory: OcrEngineFactory,
    watcher_status: WatcherStatus,
    worker_pool_running: bool,
    worker_pool_active_count: int,
) -> list[HealthCheckResult]:
    """Runs every check and returns all results, even if some raise —
    one check failing unexpectedly must never hide the results of the
    others (the whole point of this page is visibility when something
    is wrong)."""
    auth_status = google_auth.status
    checks = [
        lambda: check_internet(),
        lambda: check_google_auth(google_auth),
        lambda: check_drive(drive_client, settings.drive.root_folder_id, auth_status),
        lambda: check_sheets(sheets_client, settings.sheets.spreadsheet_id, auth_status),
        lambda: check_ocr(ocr_engine_factory),
        lambda: check_disk_space(Path(settings.watch_folder or ".")),
        lambda: check_folder_permissions(settings),
        lambda: check_database_connection(jobs_repo),
        lambda: check_watcher(watcher_status),
        lambda: check_background_workers(worker_pool_running, worker_pool_active_count),
    ]

    results: list[HealthCheckResult] = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - a broken check must not blank the rest of the page
            results.append(
                HealthCheckResult(
                    name="Unknown check",
                    status=HealthStatus.FAILED,
                    message=f"Check itself failed unexpectedly: {exc}",
                )
            )
    return results

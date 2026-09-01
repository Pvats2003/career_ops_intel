"""Application bootstrap: wires every service together (composition root).

This is the one place allowed to know about every layer at once — config,
DB, services, workers, and UI. Everything else receives its dependencies
through constructor injection, which is what keeps the rest of the codebase
independently testable.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from instacore_sync.core.config import (
    AppSettings,
    reset_settings_to_defaults,
    settings_dir,
    user_data_dir,
)
from instacore_sync.core.constants import APP_NAME, APP_ORG
from instacore_sync.core.di import ServiceContainer
from instacore_sync.core.logging_setup import configure_logging, get_logger
from instacore_sync.core.resource_paths import icon_path
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.db.repositories.settings_repository import (
    DriveFolderCacheRepository,
    SettingsRepository,
)
from instacore_sync.services.backup.backup_service import (
    BackupPaths,
    create_backup,
    prune_old_backups,
)
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.drive.drive_auth import GoogleAuthService
from instacore_sync.services.drive.drive_client import DriveClient
from instacore_sync.services.hashing.hash_service import HashService
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.pipeline.pipeline_orchestrator import PipelineOrchestrator
from instacore_sync.services.sheets.sheets_client import SheetsClient
from instacore_sync.ui.main_window import MainWindow
from instacore_sync.ui.safe_mode_window import SafeModeWindow
from instacore_sync.ui.theme.theme_manager import ThemeManager
from instacore_sync.ui.wizard.first_run_wizard import FirstRunWizard
from instacore_sync.workers.pipeline_thread import PipelineThread
from instacore_sync.workers.signals import PipelineSignalBus

logger = get_logger(__name__)

_STATS_POLL_INTERVAL_MS = 2000


class InstacoreSyncApp:
    """Owns the QApplication and every long-lived service for the process."""

    def __init__(self) -> None:
        self.settings = AppSettings.load()
        configure_logging(user_data_dir(), self.settings.app.log_level)
        logger.info("app.settings_loaded", watch_folder=self.settings.watch_folder)

        self.container = ServiceContainer()
        self._wire_services()

    def _wire_services(self) -> None:
        c = self.container
        s = self.settings

        database = Database(s.db_path)
        c.register(Database, database)

        jobs_repo = JobsRepository(database)
        logs_repo = LogsRepository(database)
        hashes_repo = HashesRepository(database)
        settings_repo = SettingsRepository(database)
        folder_cache_repo = DriveFolderCacheRepository(database)
        c.register(JobsRepository, jobs_repo)
        c.register(LogsRepository, logs_repo)
        c.register(HashesRepository, hashes_repo)
        c.register(SettingsRepository, settings_repo)
        c.register(DriveFolderCacheRepository, folder_cache_repo)

        hash_service = HashService()
        dedup_service = DedupService(hash_service, hashes_repo)
        c.register(HashService, hash_service)
        c.register(DedupService, dedup_service)

        ocr_engine_factory = OcrEngineFactory(s.ocr)
        c.register(OcrEngineFactory, ocr_engine_factory)

        google_auth = GoogleAuthService(s.credentials_path, s.token_path)
        drive_client = DriveClient(s.drive, folder_cache_repo, google_auth.get_credentials)
        sheets_client = SheetsClient(s.sheets, google_auth.get_credentials)
        c.register(GoogleAuthService, google_auth)
        c.register(DriveClient, drive_client)
        c.register(SheetsClient, sheets_client)

        signal_bus = PipelineSignalBus()
        c.register(PipelineSignalBus, signal_bus)

        orchestrator = PipelineOrchestrator(
            settings=s,
            jobs_repo=jobs_repo,
            logs_repo=logs_repo,
            dedup_service=dedup_service,
            ocr_engine_factory=ocr_engine_factory,
            google_auth=google_auth,
            drive_client=drive_client,
            sheets_client=sheets_client,
            event_sink=signal_bus,
        )
        c.register(PipelineOrchestrator, orchestrator)

        pipeline_thread = PipelineThread(orchestrator, signal_bus)
        c.register(PipelineThread, pipeline_thread)

        theme_manager = ThemeManager()
        c.register(ThemeManager, theme_manager)

    def run(self, qt_app: QApplication) -> int:
        """Show the real main window and run the Qt event loop.

        Takes an already-constructed `QApplication` rather than creating
        one itself: `run_application()` below owns the QApplication's
        lifetime so it can retry `InstacoreSyncApp()` construction (Safe
        Mode's "Retry Startup") without tearing down and recreating the
        whole Qt runtime on every attempt.
        """
        c = self.container
        pipeline_thread = c.resolve(PipelineThread)
        pipeline_thread.start()

        icon_file = icon_path()
        app_icon = QIcon(str(icon_file)) if icon_file.exists() else None

        settings_repo = c.resolve(SettingsRepository)
        if settings_repo.get("onboarding_complete") != "true":
            self._run_first_run_wizard(c, pipeline_thread, app_icon, settings_repo)

        main_window = MainWindow(
            settings=self.settings,
            signal_bus=c.resolve(PipelineSignalBus),
            pipeline_thread=pipeline_thread,
            jobs_repo=c.resolve(JobsRepository),
            logs_repo=c.resolve(LogsRepository),
            google_auth=c.resolve(GoogleAuthService),
            theme_manager=c.resolve(ThemeManager),
        )

        stats_timer = QTimer()
        stats_timer.timeout.connect(pipeline_thread.request_stats_refresh)
        stats_timer.start(_STATS_POLL_INTERVAL_MS)

        main_window.show()
        # Deferred so a slow backup (a large database) never delays the
        # window a user is waiting to see appearing on screen.
        QTimer.singleShot(2000, lambda: self._maybe_run_automatic_backup(settings_repo))

        exit_code = qt_app.exec()

        pipeline_thread.stop()
        return exit_code

    def _run_first_run_wizard(
        self,
        container: ServiceContainer,
        pipeline_thread: PipelineThread,
        app_icon: QIcon | None,
        settings_repo: SettingsRepository,
    ) -> None:
        """Shown once, before `MainWindow`, until the user finishes it —
        see `ui/wizard/first_run_wizard.py`'s module docstring. Waits for
        the pipeline thread's event loop to actually be running first:
        the wizard's live checks (sign-in, Drive/Sheets verification, OCR
        test, test upload) are all scheduled onto it."""
        pipeline_thread.wait_until_ready()
        wizard = FirstRunWizard(
            self.settings, container.resolve(PipelineSignalBus), pipeline_thread, app_icon
        )
        if wizard.exec() == FirstRunWizard.DialogCode.Accepted:
            wizard.apply_to_settings()
            settings_repo.set("onboarding_complete", "true")

    def _maybe_run_automatic_backup(self, settings_repo: SettingsRepository) -> None:
        """Runs a full backup (settings + database + logs) if the last
        one is older than `auto_backup_interval_days`, or none has ever
        run. A backup failure must never be treated as an app failure —
        this is a convenience safety net, not core functionality, so any
        error here is logged and swallowed rather than surfaced."""
        interval_days = self.settings.app.auto_backup_interval_days
        if interval_days <= 0:
            return
        try:
            last_at_raw = settings_repo.get("last_auto_backup_at")
            last_at = datetime.fromisoformat(last_at_raw) if last_at_raw else None
            if last_at is not None and datetime.now() - last_at < timedelta(days=interval_days):
                return

            paths = BackupPaths(
                settings_file=self.settings.settings_file_path,
                database_file=self.settings.db_path,
                logs_dir=self.settings.logs_dir,
                backups_dir=self.settings.backups_dir,
            )
            create_backup(paths)
            prune_old_backups(paths.backups_dir, keep=self.settings.app.auto_backup_keep_count)
            settings_repo.set("last_auto_backup_at", datetime.now().isoformat())
        except Exception:  # noqa: BLE001 - a backup failure must never look like an app crash
            logger.exception("app.automatic_backup_failed")


def _best_effort_settings_dir() -> Path | None:
    try:
        return settings_dir()
    except Exception:  # noqa: BLE001 - Safe Mode's own diagnostics must never themselves raise
        return None


def _best_effort_log_path() -> Path | None:
    try:
        return user_data_dir() / "logs" / "instacore_sync.log"
    except Exception:  # noqa: BLE001
        return None


def _log_startup_failure(detail: str) -> None:
    """Record the failure that sent us to Safe Mode, without assuming
    `configure_logging()` ever got a chance to run (it may be exactly
    what failed, or something before it did)."""
    try:
        configure_logging(user_data_dir(), "INFO")
        get_logger(__name__).error("app.startup_failed", traceback=detail)
    except Exception:  # noqa: BLE001
        # Truly last resort: stderr, so at least a terminal-launched dev
        # build (or a bug report with Windows Event Viewer / a redirected
        # console) has *something*. Never let this raise further.
        print("InstaCore Sync failed to start:", file=sys.stderr)  # noqa: T201
        print(detail, file=sys.stderr)  # noqa: T201


def run_application() -> int:
    """Composition root's entry point: owns the QApplication for the
    whole process lifetime, including across Safe Mode retries.

    On any exception constructing `InstacoreSyncApp()` (settings failed
    to load/validate, the database couldn't be opened, a service failed
    to construct), shows `SafeModeWindow` instead of letting the app
    crash before a single window ever appears. "Retry Startup" attempts
    `InstacoreSyncApp()` again in a fresh loop iteration; "Quit" exits.
    """
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_ORG)
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(True)

    icon_file = icon_path()
    app_icon = QIcon(str(icon_file)) if icon_file.exists() else QIcon()
    if not app_icon.isNull():
        qt_app.setWindowIcon(app_icon)

    while True:
        try:
            instacore_app = InstacoreSyncApp()
        except Exception as exc:  # noqa: BLE001 - this is precisely the "never crash on startup" boundary
            if _show_safe_mode_and_wait(qt_app, app_icon, exc) == "retry":
                continue
            return 1
        else:
            return instacore_app.run(qt_app)


def _show_safe_mode_and_wait(qt_app: QApplication, app_icon: QIcon, exc: Exception) -> str:
    """Shows Safe Mode for one failed startup attempt and blocks (via a
    nested `qt_app.exec()`) until the user picks Retry or Quit. Factored
    out of `run_application`'s loop so the button-click closures below
    close over locals scoped to *this* call, not to a variable that's
    rebound on every loop iteration (which is also what a stray Retry
    click delivered after this call already returned would ever be able
    to affect -- it can't, `on_retry`/`on_quit` are dead once this
    function returns).
    """
    detail = traceback.format_exc()
    _log_startup_failure(detail)

    outcome = "quit"

    def _retry() -> None:
        nonlocal outcome
        outcome = "retry"
        safe_window.close()

    def _quit() -> None:
        nonlocal outcome
        outcome = "quit"
        safe_window.close()

    safe_window = SafeModeWindow(
        error_summary=str(exc) or type(exc).__name__,
        error_detail=detail,
        settings_dir=_best_effort_settings_dir(),
        log_path=_best_effort_log_path(),
        on_retry=_retry,
        on_reset_settings=_safe_reset_settings,
        on_quit=_quit,
        app_icon=app_icon if not app_icon.isNull() else None,
    )
    safe_window.show()
    qt_app.exec()
    return outcome


def _safe_reset_settings() -> bool:
    try:
        reset_settings_to_defaults()
        return True
    except Exception:  # noqa: BLE001 - reported to the user by the caller, must not raise further
        logger.exception("app.reset_settings_failed")
        return False


def run() -> int:
    return run_application()

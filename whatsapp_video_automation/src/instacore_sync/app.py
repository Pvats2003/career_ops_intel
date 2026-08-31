"""Application bootstrap: wires every service together (composition root).

This is the one place allowed to know about every layer at once — config,
DB, services, workers, and UI. Everything else receives its dependencies
through constructor injection, which is what keeps the rest of the codebase
independently testable.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from instacore_sync.core.config import AppSettings, user_data_dir
from instacore_sync.core.constants import APP_NAME, APP_ORG
from instacore_sync.core.di import ServiceContainer
from instacore_sync.core.logging_setup import configure_logging, get_logger
from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.db.repositories.settings_repository import (
    DriveFolderCacheRepository,
    SettingsRepository,
)
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.drive.drive_auth import GoogleAuthService
from instacore_sync.services.drive.drive_client import DriveClient
from instacore_sync.services.hashing.hash_service import HashService
from instacore_sync.services.ocr.engine_factory import OcrEngineFactory
from instacore_sync.services.pipeline.pipeline_orchestrator import PipelineOrchestrator
from instacore_sync.services.sheets.sheets_client import SheetsClient
from instacore_sync.ui.main_window import MainWindow
from instacore_sync.ui.theme.theme_manager import ThemeManager
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

    def run(self) -> int:
        QApplication.setApplicationName(APP_NAME)
        QApplication.setOrganizationName(APP_ORG)
        qt_app = QApplication(sys.argv)
        qt_app.setQuitOnLastWindowClosed(True)

        c = self.container
        main_window = MainWindow(
            settings=self.settings,
            signal_bus=c.resolve(PipelineSignalBus),
            pipeline_thread=c.resolve(PipelineThread),
            jobs_repo=c.resolve(JobsRepository),
            logs_repo=c.resolve(LogsRepository),
            google_auth=c.resolve(GoogleAuthService),
            theme_manager=c.resolve(ThemeManager),
        )

        pipeline_thread = c.resolve(PipelineThread)
        pipeline_thread.start()

        stats_timer = QTimer()
        stats_timer.timeout.connect(pipeline_thread.request_stats_refresh)
        stats_timer.start(_STATS_POLL_INTERVAL_MS)

        main_window.show()
        exit_code = qt_app.exec()

        pipeline_thread.stop()
        return exit_code


def run() -> int:
    return InstacoreSyncApp().run()

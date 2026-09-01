"""Application shell: sidebar navigation, top status bar, and page stack."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from instacore_sync import __version__
from instacore_sync.core.config import AppSettings
from instacore_sync.core.constants import APP_NAME
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.core.resource_paths import icon_path
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.db.repositories.logs_repository import LogsRepository
from instacore_sync.domain.enums import GoogleAuthStatus, JobStatus, OcrEngineStatus, WatcherStatus
from instacore_sync.domain.models import UploadLogEntry
from instacore_sync.services.drive.drive_auth import GoogleAuthService
from instacore_sync.ui.theme.theme_manager import ThemeManager
from instacore_sync.ui.viewmodels.dashboard_viewmodel import DashboardViewModel
from instacore_sync.ui.views.dashboard_view import DashboardView
from instacore_sync.ui.views.health_check_view import HealthCheckView
from instacore_sync.ui.views.logs_view import LogsView
from instacore_sync.ui.views.needs_review_view import NeedsReviewView
from instacore_sync.ui.views.queue_view import QueueView
from instacore_sync.ui.views.settings_view import SettingsView
from instacore_sync.ui.wizard.first_run_wizard import FirstRunWizard
from instacore_sync.workers.pipeline_thread import PipelineThread
from instacore_sync.workers.signals import PipelineSignalBus

logger = get_logger(__name__)


def _load_app_icon() -> QIcon:
    """Best-effort load of the bundled application icon. Missing (a dev
    checkout that hasn't run `packaging/generate_icon.py`, or an
    unexpected packaging layout) must never be fatal -- Qt is perfectly
    happy with a null QIcon, it just falls back to a generic window/tray
    icon, which is a cosmetic gap worth catching in QA, not a crash."""
    path = icon_path()
    if not path.exists():
        logger.warning("main_window.icon_not_found", path=str(path))
        return QIcon()
    return QIcon(str(path))


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: AppSettings,
        signal_bus: PipelineSignalBus,
        pipeline_thread: PipelineThread,
        jobs_repo: JobsRepository,
        logs_repo: LogsRepository,
        google_auth: GoogleAuthService,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._signals = signal_bus
        self._pipeline_thread = pipeline_thread
        self._theme = theme_manager
        self._is_paused = False

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)
        self._app_icon = _load_app_icon()
        self.setWindowIcon(self._app_icon)

        central = QWidget()
        central.setObjectName("AppBackground")
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(0)
        right_column.addWidget(self._build_top_bar())

        self._stack = QStackedWidget()
        self._dashboard_vm = DashboardViewModel(signal_bus)
        self._dashboard_view = DashboardView(self._dashboard_vm, signal_bus)
        self._queue_view = QueueView(jobs_repo, signal_bus, pipeline_thread)
        self._needs_review_view = NeedsReviewView(jobs_repo, signal_bus, pipeline_thread, settings)
        self._logs_view = LogsView(logs_repo)
        self._health_check_view = HealthCheckView(signal_bus, pipeline_thread)
        self._settings_view = SettingsView(
            settings,
            theme_manager,
            self._on_theme_changed,
            pipeline_thread.sign_in_interactively,
            self._on_rerun_wizard_clicked,
        )

        for view in (
            self._dashboard_view,
            self._queue_view,
            self._needs_review_view,
            self._logs_view,
            self._health_check_view,
            self._settings_view,
        ):
            self._stack.addWidget(view)

        right_column.addWidget(self._stack, stretch=1)
        root_layout.addLayout(right_column, stretch=1)

        signal_bus.watcher_status_changed.connect(self._on_watcher_status)
        signal_bus.auth_status_changed.connect(self._on_auth_status)
        signal_bus.ocr_engine_status_changed.connect(self._on_ocr_status)
        signal_bus.pause_state_changed.connect(self._on_pause_state_changed)
        signal_bus.log_entry_added.connect(self._on_log_entry_for_notification)

        self._setup_tray_icon()
        self._theme.apply(central, settings.app.theme)

    # -- sidebar ----------------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        brand = QLabel(APP_NAME)
        brand.setObjectName("SidebarBrand")
        layout.addWidget(brand)

        subtitle = QLabel(f"Instacore video automation · v{__version__}")
        subtitle.setObjectName("SidebarSubtitle")
        layout.addWidget(subtitle)

        self._nav_group = QButtonGroup(sidebar)
        self._nav_group.setExclusive(True)

        nav_items = [
            ("📊  Dashboard", 0),
            ("📁  Upload Queue", 1),
            ("🔍  Needs Review", 2),
            ("🧾  Logs", 3),
            ("🩺  Health Check", 4),
            ("⚙️  Settings", 5),
        ]
        for label, index in nav_items:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked, i=index: self._stack.setCurrentIndex(i))
            self._nav_group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)
        return sidebar

    # -- top status bar -----------------------------------------------------------

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(24)

        self._watcher_label = self._status_item("Folder Watcher")
        self._auth_label = self._status_item("Google Account")
        self._ocr_label = self._status_item("OCR Engine")

        layout.addWidget(self._watcher_label["container"])
        layout.addWidget(self._auth_label["container"])
        layout.addWidget(self._ocr_label["container"])
        layout.addStretch(1)

        self._pause_button = QPushButton("⏸  Pause Uploads")
        self._pause_button.setToolTip(
            "Stop starting new uploads. Anything already in flight finishes normally."
        )
        self._pause_button.clicked.connect(self._on_pause_button_clicked)
        layout.addWidget(self._pause_button)

        return bar

    def _on_pause_button_clicked(self) -> None:
        # The real pause state lives on the worker pool, owned by the
        # pipeline's own asyncio thread — we don't query it synchronously
        # from the GUI thread (that would be a cross-thread race). Instead
        # we track our own local flag, kept authoritative by
        # `_on_pause_state_changed`, which fires once the orchestrator has
        # actually applied the change.
        if self._is_paused:
            self._pipeline_thread.resume_uploads()
        else:
            self._pipeline_thread.pause_uploads()

    def _on_pause_state_changed(self, is_paused: bool) -> None:
        self._is_paused = is_paused
        if is_paused:
            self._pause_button.setText("▶  Resume Uploads")
            self._pause_button.setObjectName("PrimaryButton")
        else:
            self._pause_button.setText("⏸  Pause Uploads")
            self._pause_button.setObjectName("")
        self._repolish(self._pause_button)

    def _status_item(self, label: str) -> dict:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        dot = QLabel("●")
        dot.setObjectName("StatusDotOff")
        text = QLabel(label)
        text.setObjectName("Muted")
        row.addWidget(dot)
        row.addWidget(text)
        return {"container": container, "dot": dot, "text": text}

    def _on_watcher_status(self, status: WatcherStatus) -> None:
        dot = self._watcher_label["dot"]
        text = self._watcher_label["text"]
        if status == WatcherStatus.RUNNING:
            dot.setObjectName("StatusDotOn")
            text.setText("Folder Watcher: Running")
        elif status == WatcherStatus.ERROR:
            dot.setObjectName("StatusDotOff")
            text.setText("Folder Watcher: Error")
        else:
            dot.setObjectName("StatusDotWarn")
            text.setText(f"Folder Watcher: {status.value.title()}")
        self._repolish(dot)

    def _on_auth_status(self, status: GoogleAuthStatus, account_email: str | None) -> None:
        dot = self._auth_label["dot"]
        text = self._auth_label["text"]
        if status == GoogleAuthStatus.AUTHENTICATED:
            dot.setObjectName("StatusDotOn")
            text.setText(f"Google: {account_email or 'Connected'}")
        elif status == GoogleAuthStatus.ERROR:
            dot.setObjectName("StatusDotOff")
            text.setText("Google: Sign-in required")
        else:
            dot.setObjectName("StatusDotWarn")
            text.setText(f"Google: {status.value.title()}")
        self._repolish(dot)

    def _on_ocr_status(self, engine_name: str, status: OcrEngineStatus) -> None:
        dot = self._ocr_label["dot"]
        text = self._ocr_label["text"]
        if status == OcrEngineStatus.READY:
            dot.setObjectName("StatusDotOn")
        elif status == OcrEngineStatus.UNAVAILABLE or status == OcrEngineStatus.ERROR:
            dot.setObjectName("StatusDotOff")
        else:
            dot.setObjectName("StatusDotWarn")
        text.setText(f"OCR ({engine_name}): {status.value.title()}")
        self._repolish(dot)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    # -- tray + notifications + theme -------------------------------------------

    def _setup_tray_icon(self) -> None:
        # Created whenever the OS supports it, independent of
        # `minimize_to_tray`: that setting only controls whether closing the
        # window hides it instead of quitting — desktop notifications for
        # failures/needs-review are a separate feature a user might want
        # even if they don't want the app living in the tray permanently.
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self._app_icon)
        self._tray.setToolTip(APP_NAME)
        self._tray.show()

    def _on_log_entry_for_notification(self, entry: UploadLogEntry) -> None:
        if not self._settings.app.notifications_enabled:
            return
        tray = getattr(self, "_tray", None)
        if tray is None:
            return

        if entry.status == JobStatus.FAILED:
            tray.showMessage(
                "Upload failed",
                f"{entry.filename}: {entry.error_message or 'Unknown error'}",
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
        elif entry.status == JobStatus.NEEDS_REVIEW:
            tray.showMessage(
                "Needs review",
                f"{entry.filename}: couldn't confidently read a Device ID. "
                "Open the Needs Review tab to resolve it.",
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )

    def _on_theme_changed(self, theme: str) -> None:
        self._settings.app.theme = theme
        self._theme.apply(self.centralWidget(), theme)
        self._settings.save()

    def _on_rerun_wizard_clicked(self) -> None:
        """Settings -> "Run Setup Wizard Again" — independent of the
        `onboarding_complete` flag app.py checks at startup; this is a
        manual re-entry point for anyone who skipped a step the first
        time, not a reset of that flag."""
        wizard = FirstRunWizard(self._settings, self._signals, self._pipeline_thread, self._app_icon)
        if wizard.exec() == FirstRunWizard.DialogCode.Accepted:
            wizard.apply_to_settings()

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._settings.app.minimize_to_tray and getattr(self, "_tray", None) is not None:
            self.hide()
            event.ignore()
            return
        logger.info("main_window.closing")
        self._pipeline_thread.stop()
        event.accept()

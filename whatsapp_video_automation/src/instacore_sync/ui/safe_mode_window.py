"""Safe Mode: shown instead of the normal app when startup fails.

Deliberately has **no dependency on anything that might itself be
broken** — not `AppSettings`, not the DI container, not any repository.
If `AppSettings.load()` raised (malformed YAML, a bad field value), or
service wiring failed (a locked/corrupted database file, a permissions
problem creating the data directory), this window still has to be able
to open and let the user see what happened and try to fix it. It never
starts the pipeline (uploads are simply never started), and it never
raises out of its own button handlers back into the caller — every
action here is wrapped so a *second* failure while trying to recover
from the first still can't crash the app.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.core.constants import APP_NAME
from instacore_sync.core.logging_setup import get_logger

logger = get_logger(__name__)


def open_in_file_explorer(path: Path) -> bool:
    """Best-effort "reveal this file/folder" — Windows Explorer via
    `os.startfile` when available (the normal case on the platform this
    app actually ships for), falling back to `xdg-open`/`open` elsewhere
    for development. Never raises; returns whether it believes it
    succeeded, since this is always called from a button handler that
    must not let a failure here compound the original startup failure."""
    try:
        if sys.platform == "win32":
            import os

            os.startfile(str(path))  # noqa: S606 - user-initiated, not attacker-controlled
            return True
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if shutil.which(opener):
            subprocess.Popen([opener, str(path)])  # noqa: S603
            return True
        return False
    except OSError as exc:
        logger.warning("safe_mode.open_path_failed", path=str(path), error=str(exc))
        return False


class SafeModeWindow(QWidget):
    """A minimal, dependency-free recovery window.

    Callers wire this to their own retry/reset logic via callbacks; this
    class only handles presentation and confirmation prompts, never
    touches `AppSettings` or the DI container directly.
    """

    def __init__(
        self,
        *,
        error_summary: str,
        error_detail: str,
        settings_dir: Path | None,
        log_path: Path | None,
        on_retry: Callable[[], None],
        on_reset_settings: Callable[[], bool],
        on_quit: Callable[[], None],
        app_icon: QIcon | None = None,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self._settings_dir = settings_dir
        self._log_path = log_path
        self._on_retry = on_retry
        self._on_reset_settings = on_reset_settings
        self._on_quit = on_quit

        self.setWindowTitle(f"{APP_NAME} — Safe Mode")
        if app_icon is not None:
            self.setWindowIcon(app_icon)
        self.resize(680, 520)
        self.setStyleSheet(
            "QWidget { background-color: #16182E; color: #E7E9F5; font-size: 13px; }"
            "QPushButton { padding: 8px 14px; border-radius: 6px; background-color: #262A4D; }"
            "QPushButton:hover { background-color: #323768; }"
            "QPlainTextEdit { background-color: #0E1020; border: 1px solid #323768; border-radius: 6px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title = QLabel(f"⚠  {APP_NAME} couldn't start normally")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        explanation = QLabel(
            "InstaCore Sync has started in Safe Mode instead of crashing. Uploads and the "
            "background pipeline are disabled while in Safe Mode. You can try to fix the "
            "problem below, then click Retry — or quit and fix it manually."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #B7BBDD;")
        root.addWidget(explanation)

        summary_label = QLabel(f"<b>What went wrong:</b> {error_summary}")
        summary_label.setWordWrap(True)
        root.addWidget(summary_label)

        detail_box = QPlainTextEdit()
        detail_box.setReadOnly(True)
        detail_box.setPlainText(error_detail)
        detail_box.setMinimumHeight(220)
        root.addWidget(detail_box, stretch=1)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        if settings_dir is not None:
            open_settings_btn = QPushButton("Open Settings Folder")
            open_settings_btn.clicked.connect(self._on_open_settings_clicked)
            button_row.addWidget(open_settings_btn)

        if log_path is not None:
            open_log_btn = QPushButton("Open Log File")
            open_log_btn.clicked.connect(self._on_open_log_clicked)
            button_row.addWidget(open_log_btn)

        reset_btn = QPushButton("Reset Settings to Defaults…")
        reset_btn.clicked.connect(self._on_reset_clicked)
        button_row.addWidget(reset_btn)

        button_row.addStretch(1)

        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(self._on_quit_clicked)
        button_row.addWidget(quit_btn)

        retry_btn = QPushButton("Retry Startup")
        retry_btn.setStyleSheet(
            "background-color: #5DE0E6; color: #0B0D1E; font-weight: 600;"
        )
        retry_btn.clicked.connect(self._on_retry_clicked)
        button_row.addWidget(retry_btn)

        root.addLayout(button_row)

    # -- handlers -------------------------------------------------------------

    def _on_open_settings_clicked(self) -> None:
        if self._settings_dir is None:
            return
        if not open_in_file_explorer(self._settings_dir):
            QMessageBox.warning(
                self, "Couldn't open folder", f"Settings folder:\n{self._settings_dir}"
            )

    def _on_open_log_clicked(self) -> None:
        if self._log_path is None:
            return
        target = self._log_path if self._log_path.exists() else self._log_path.parent
        if not open_in_file_explorer(target):
            QMessageBox.warning(self, "Couldn't open log", f"Log file:\n{self._log_path}")

    def _on_reset_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset settings to defaults?",
            "This replaces your settings.local.yaml with the default template. Your "
            "processed videos, upload history, and Google sign-in are not affected -- "
            "only app configuration (folders, Drive/Sheets IDs, OCR/upload options).\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            succeeded = self._on_reset_settings()
        except Exception as exc:  # noqa: BLE001 - a failed recovery attempt must not crash Safe Mode itself
            logger.exception("safe_mode.reset_settings_failed")
            QMessageBox.critical(self, "Reset failed", str(exc))
            return
        if succeeded:
            QMessageBox.information(
                self, "Settings reset", "Settings were reset. Click Retry Startup to try again."
            )
        else:
            QMessageBox.warning(self, "Reset failed", "Could not reset settings. See the log file.")

    def _on_retry_clicked(self) -> None:
        self._on_retry()

    def _on_quit_clicked(self) -> None:
        self._on_quit()

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        # Closing via the window's X button is the same as choosing Quit --
        # there is no pipeline running to lose work from, so there's no
        # reason to intercept this the way MainWindow intercepts close for
        # "minimize to tray".
        self._on_quit()
        event.accept()

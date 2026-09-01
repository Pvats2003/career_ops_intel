"""Settings screen — edits the same `AppSettings` object the pipeline reads,
persisted to `config/settings.local.yaml` via `AppSettings.save()`.

Changes to folders/OCR/upload concurrency take effect on next pipeline
start (a full restart of the background thread); this is called out in the
UI rather than attempting a risky hot-reload of an in-flight worker pool.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from instacore_sync.core.config import AppSettings
from instacore_sync.core.exceptions import ConfigurationError
from instacore_sync.domain.enums import OcrEngineName
from instacore_sync.services.backup.backup_service import BackupPaths, create_backup, restore_backup
from instacore_sync.ui.theme.theme_manager import ThemeManager


def _folder_row(initial: str, on_browse_title: str) -> tuple[QWidget, QLineEdit]:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    line_edit = QLineEdit(initial)
    browse_button = QPushButton("Browse…")

    def _browse() -> None:
        chosen = QFileDialog.getExistingDirectory(container, on_browse_title, line_edit.text())
        if chosen:
            line_edit.setText(chosen)

    browse_button.clicked.connect(_browse)
    layout.addWidget(line_edit, stretch=1)
    layout.addWidget(browse_button)
    return container, line_edit


class SettingsView(QWidget):
    def __init__(
        self,
        settings: AppSettings,
        theme_manager: ThemeManager,
        on_theme_changed: Callable[[str], None],
        on_sign_in_clicked: Callable[[], None] | None = None,
        on_rerun_wizard: Callable[[], None] | None = None,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme_manager = theme_manager
        self._on_theme_changed = on_theme_changed
        self._on_sign_in_clicked = on_sign_in_clicked
        self._on_rerun_wizard = on_rerun_wizard

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QVBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Folders, Google integration, OCR engine, and upload behavior")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_folders_tab(), "Folders")
        tabs.addTab(self._build_drive_tab(), "Google Drive")
        tabs.addTab(self._build_sheets_tab(), "Google Sheets")
        tabs.addTab(self._build_ocr_tab(), "OCR Engine")
        tabs.addTab(self._build_uploads_tab(), "Uploads")
        root.addWidget(tabs, stretch=1)

        footer = QHBoxLayout()
        export_button = QPushButton("Export Settings…")
        export_button.setToolTip("Save folders, Drive/Sheets IDs, OCR and upload settings to a file")
        export_button.clicked.connect(self._on_export_clicked)
        footer.addWidget(export_button)

        import_button = QPushButton("Import Settings…")
        import_button.setToolTip(
            "Load settings from a previously exported file. Google sign-in is not included\n"
            "and must be redone on this machine after importing."
        )
        import_button.clicked.connect(self._on_import_clicked)
        footer.addWidget(import_button)

        backup_button = QPushButton("Backup Now…")
        backup_button.setToolTip(
            "Creates a full backup: settings, the database (upload history, queue), and logs."
        )
        backup_button.clicked.connect(self._on_backup_now_clicked)
        footer.addWidget(backup_button)

        restore_button = QPushButton("Restore from Backup…")
        restore_button.setToolTip("Restores settings, database, and logs from a backup file.")
        restore_button.clicked.connect(self._on_restore_clicked)
        footer.addWidget(restore_button)

        footer.addStretch(1)
        save_button = QPushButton("Save Settings")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save)
        footer.addWidget(save_button)
        root.addLayout(footer)

    # -- tabs ----------------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        self._theme_combo.setCurrentText(self._settings.app.theme)
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow("Theme", self._theme_combo)

        self._auto_start_check = QCheckBox("Launch automatically when Windows starts")
        self._auto_start_check.setChecked(self._settings.app.auto_start_with_windows)
        form.addRow("Auto start", self._auto_start_check)

        self._notifications_check = QCheckBox("Show desktop notifications for failures / needs review")
        self._notifications_check.setChecked(self._settings.app.notifications_enabled)
        form.addRow("Notifications", self._notifications_check)

        self._tray_check = QCheckBox("Minimize to system tray instead of closing")
        self._tray_check.setChecked(self._settings.app.minimize_to_tray)
        form.addRow("System tray", self._tray_check)

        self._log_level_combo = QComboBox()
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level_combo.setCurrentText(self._settings.app.log_level)
        form.addRow("Log level", self._log_level_combo)

        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(0, 3650)
        self._retention_spin.setSuffix(" days")
        self._retention_spin.setSpecialValueText("Never")
        self._retention_spin.setValue(self._settings.app.jobs_retention_days)
        self._retention_spin.setToolTip(
            "Completed/duplicate entries older than this are cleaned up on startup.\n"
            "Failed and Needs Review items are never auto-removed."
        )
        form.addRow("Keep completed history for", self._retention_spin)

        if self._on_rerun_wizard is not None:
            rerun_wizard_button = QPushButton("Run Setup Wizard Again…")
            rerun_wizard_button.setToolTip(
                "Re-opens the guided setup (folders, Google sign-in, Drive/Sheets, OCR and "
                "upload tests) — useful if you skipped a step the first time."
            )
            rerun_wizard_button.clicked.connect(self._on_rerun_wizard)
            form.addRow("Setup wizard", rerun_wizard_button)

        return widget

    def _build_folders_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        watch_row, self._watch_folder_edit = _folder_row(
            self._settings.watch_folder, "Select WhatsApp download folder"
        )
        processed_row, self._processed_folder_edit = _folder_row(
            self._settings.processed_folder, "Select Processed folder"
        )
        review_row, self._review_folder_edit = _folder_row(
            self._settings.needs_review_folder, "Select Needs Review folder"
        )
        failed_row, self._failed_folder_edit = _folder_row(
            self._settings.failed_folder, "Select Failed folder"
        )

        form.addRow("WhatsApp folder", watch_row)
        form.addRow("Processed folder", processed_row)
        form.addRow("Needs Review folder", review_row)
        form.addRow("Failed folder", failed_row)
        return widget

    def _build_drive_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self._root_folder_edit = QLineEdit(self._settings.drive.root_folder_id)
        self._shared_drive_edit = QLineEdit(self._settings.drive.shared_drive_id)
        self._date_format_edit = QLineEdit(self._settings.drive.date_folder_format)
        self._public_link_check = QCheckBox("Set \"Anyone with the link\" on every upload")
        self._public_link_check.setChecked(self._settings.drive.make_public_link)
        self._credentials_edit = QLineEdit(self._settings.drive.credentials_file)

        form.addRow("Root folder ID", self._root_folder_edit)
        form.addRow("Shared Drive ID (optional)", self._shared_drive_edit)
        form.addRow("Date folder format", self._date_format_edit)
        form.addRow("Link sharing", self._public_link_check)
        form.addRow("credentials.json path", self._credentials_edit)

        sign_in_button = QPushButton("Sign in with Google…")
        sign_in_button.setToolTip(
            "Opens a browser window to sign in (or switch accounts). InstaCore Sync never\n"
            "opens this automatically — it only runs when you click this button, so it never\n"
            "blocks startup waiting on a browser you didn't ask for."
        )
        sign_in_button.clicked.connect(self._on_sign_in)
        form.addRow("Google account", sign_in_button)
        return widget

    def _build_sheets_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self._spreadsheet_id_edit = QLineEdit(self._settings.sheets.spreadsheet_id)
        self._worksheet_edit = QLineEdit(self._settings.sheets.worksheet_name)
        self._header_row_spin = QSpinBox()
        self._header_row_spin.setRange(1, 100)
        self._header_row_spin.setValue(self._settings.sheets.header_row)

        form.addRow("Spreadsheet ID", self._spreadsheet_id_edit)
        form.addRow("Worksheet name", self._worksheet_edit)
        form.addRow("Header row", self._header_row_spin)

        cols = self._settings.sheets.columns
        self._col_edits = {
            "date": QLineEdit(cols.date),
            "device_id": QLineEdit(cols.device_id),
            "filename": QLineEdit(cols.filename),
            "drive_link": QLineEdit(cols.drive_link),
            "status": QLineEdit(cols.status),
            "uploaded_at": QLineEdit(cols.uploaded_at),
            "ocr_confidence": QLineEdit(cols.ocr_confidence),
        }
        for label, edit in self._col_edits.items():
            edit.setMaximumWidth(60)
            form.addRow(f"Column: {label.replace('_', ' ').title()}", edit)

        return widget

    def _build_ocr_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self._ocr_engine_combo = QComboBox()
        self._ocr_engine_combo.addItem("Tesseract (fast, default)", OcrEngineName.TESSERACT)
        self._ocr_engine_combo.addItem("PaddleOCR (heavier, often more accurate)", OcrEngineName.PADDLEOCR)
        self._ocr_engine_combo.addItem("Auto (try both, keep best)", OcrEngineName.AUTO)
        index = self._ocr_engine_combo.findData(self._settings.ocr.engine)
        self._ocr_engine_combo.setCurrentIndex(max(0, index))

        self._min_confidence_spin = QDoubleSpinBox()
        self._min_confidence_spin.setRange(0.0, 1.0)
        self._min_confidence_spin.setSingleStep(0.05)
        self._min_confidence_spin.setValue(self._settings.ocr.min_confidence)

        self._max_seconds_spin = QDoubleSpinBox()
        self._max_seconds_spin.setRange(0.5, 60.0)
        self._max_seconds_spin.setValue(self._settings.ocr.max_seconds_scanned)

        self._frame_interval_spin = QDoubleSpinBox()
        self._frame_interval_spin.setRange(0.1, 5.0)
        self._frame_interval_spin.setSingleStep(0.1)
        self._frame_interval_spin.setValue(self._settings.ocr.frame_interval_seconds)

        self._full_scan_check = QCheckBox("Scan whole video as a last resort if low-confidence")
        self._full_scan_check.setChecked(self._settings.ocr.full_scan_on_low_confidence)

        self._tesseract_cmd_edit = QLineEdit(self._settings.ocr.tesseract_cmd)
        self._device_pattern_edit = QLineEdit(self._settings.ocr.device_id_pattern)

        form.addRow("OCR engine", self._ocr_engine_combo)
        form.addRow("Minimum confidence", self._min_confidence_spin)
        form.addRow("Max seconds scanned", self._max_seconds_spin)
        form.addRow("Frame sampling interval (s)", self._frame_interval_spin)
        form.addRow("Full-scan fallback", self._full_scan_check)
        form.addRow("tesseract.exe path (optional)", self._tesseract_cmd_edit)
        form.addRow("Device ID pattern (regex)", self._device_pattern_edit)
        return widget

    def _build_uploads_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setRange(1, 40)
        self._concurrency_spin.setValue(self._settings.uploads.max_concurrent)

        self._retry_count_spin = QSpinBox()
        self._retry_count_spin.setRange(1, 20)
        self._retry_count_spin.setValue(self._settings.uploads.retry_count)

        self._retry_backoff_spin = QDoubleSpinBox()
        self._retry_backoff_spin.setRange(0.5, 60.0)
        self._retry_backoff_spin.setValue(self._settings.uploads.retry_backoff_seconds)

        self._chunk_size_spin = QSpinBox()
        self._chunk_size_spin.setRange(1, 100)
        self._chunk_size_spin.setValue(self._settings.uploads.chunk_size_mb)

        self._dedup_check = QCheckBox("Skip videos whose SHA-256 hash was already uploaded")
        self._dedup_check.setChecked(self._settings.uploads.duplicate_check)

        form.addRow("Concurrent uploads", self._concurrency_spin)
        form.addRow("Retry attempts", self._retry_count_spin)
        form.addRow("Retry backoff (seconds)", self._retry_backoff_spin)
        form.addRow("Upload chunk size (MB)", self._chunk_size_spin)
        form.addRow("Duplicate detection", self._dedup_check)
        return widget

    # -- Google sign-in -------------------------------------------------------

    def _on_sign_in(self) -> None:
        if self._on_sign_in_clicked is None:
            return
        self._on_sign_in_clicked()
        QMessageBox.information(
            self,
            "Signing in",
            "A browser window should open to complete Google sign-in. Watch the status "
            "indicator at the top of the window — it updates once sign-in finishes.",
        )

    # -- backup / restore ---------------------------------------------------------

    def _on_export_clicked(self) -> None:
        default_path = str(Path.home() / "instacore_sync_settings_backup.yaml")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Settings", default_path, "YAML Files (*.yaml)"
        )
        if not path_str:
            return
        try:
            self._settings.export_backup(Path(path_str))
            QMessageBox.information(self, "Export complete", f"Settings exported to:\n{path_str}")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _on_import_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import Settings", str(Path.home()), "YAML Files (*.yaml)"
        )
        if not path_str:
            return

        try:
            imported = AppSettings.load_backup(Path(path_str))
        except Exception as exc:  # noqa: BLE001 - arbitrary user-selected file; report, don't crash
            QMessageBox.critical(
                self, "Import failed", f"Could not read that file as InstaCore Sync settings:\n{exc}"
            )
            return

        confirm = QMessageBox.question(
            self,
            "Import settings",
            "This will replace your current settings (folders, Drive/Sheets IDs, OCR, and upload "
            "options).\nGoogle sign-in is not included — you'll need to sign in again if the "
            "account changes.\n\nContinue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._settings.update_from(imported)
        self._settings.save()
        QMessageBox.information(
            self,
            "Import complete",
            "Settings imported and saved. Restart InstaCore Sync for the changes to take full effect.",
        )

    # -- full backup / restore (settings + database + logs) ---------------------

    def _backup_paths(self) -> BackupPaths:
        s = self._settings
        return BackupPaths(
            settings_file=s.settings_file_path,
            database_file=s.db_path,
            logs_dir=s.logs_dir,
            backups_dir=s.backups_dir,
        )

    def _on_backup_now_clicked(self) -> None:
        try:
            zip_path = create_backup(self._backup_paths())
        except OSError as exc:
            QMessageBox.critical(self, "Backup failed", str(exc))
            return
        QMessageBox.information(
            self, "Backup complete", f"Settings, database, and logs were backed up to:\n{zip_path}"
        )

    def _on_restore_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Restore from Backup", str(self._settings.backups_dir), "Backup Files (*.zip)"
        )
        if not path_str:
            return

        confirm = QMessageBox.question(
            self,
            "Restore from backup?",
            "This replaces your current settings, database (upload history and queue), and logs "
            "with the contents of this backup. This cannot be undone.\n\n"
            "InstaCore Sync must be restarted afterward for the restored data to load — do not "
            "continue if the pipeline is mid-upload.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            restore_backup(Path(path_str), self._backup_paths())
        except (ConfigurationError, OSError) as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return

        QMessageBox.information(
            self,
            "Restore complete",
            "Backup restored. Close and restart InstaCore Sync now to load the restored data.",
        )

    # -- persistence ------------------------------------------------------------

    def _save(self) -> None:
        s = self._settings

        s.app.theme = self._theme_combo.currentText()
        s.app.auto_start_with_windows = self._auto_start_check.isChecked()
        s.app.notifications_enabled = self._notifications_check.isChecked()
        s.app.minimize_to_tray = self._tray_check.isChecked()
        s.app.log_level = self._log_level_combo.currentText()
        s.app.jobs_retention_days = self._retention_spin.value()

        s.watch_folder = self._watch_folder_edit.text().strip()
        s.processed_folder = self._processed_folder_edit.text().strip()
        s.needs_review_folder = self._review_folder_edit.text().strip()
        s.failed_folder = self._failed_folder_edit.text().strip()
        for folder in (s.processed_folder, s.needs_review_folder, s.failed_folder):
            if folder:
                Path(folder).mkdir(parents=True, exist_ok=True)

        s.drive.root_folder_id = self._root_folder_edit.text().strip()
        s.drive.shared_drive_id = self._shared_drive_edit.text().strip()
        s.drive.date_folder_format = self._date_format_edit.text().strip() or "%d %b %Y"
        s.drive.make_public_link = self._public_link_check.isChecked()
        s.drive.credentials_file = self._credentials_edit.text().strip()

        s.sheets.spreadsheet_id = self._spreadsheet_id_edit.text().strip()
        s.sheets.worksheet_name = self._worksheet_edit.text().strip()
        s.sheets.header_row = self._header_row_spin.value()
        s.sheets.columns.date = self._col_edits["date"].text().strip().upper()
        s.sheets.columns.device_id = self._col_edits["device_id"].text().strip().upper()
        s.sheets.columns.filename = self._col_edits["filename"].text().strip().upper()
        s.sheets.columns.drive_link = self._col_edits["drive_link"].text().strip().upper()
        s.sheets.columns.status = self._col_edits["status"].text().strip().upper()
        s.sheets.columns.uploaded_at = self._col_edits["uploaded_at"].text().strip().upper()
        s.sheets.columns.ocr_confidence = self._col_edits["ocr_confidence"].text().strip().upper()

        s.ocr.engine = self._ocr_engine_combo.currentData()
        s.ocr.min_confidence = self._min_confidence_spin.value()
        s.ocr.max_seconds_scanned = self._max_seconds_spin.value()
        s.ocr.frame_interval_seconds = self._frame_interval_spin.value()
        s.ocr.full_scan_on_low_confidence = self._full_scan_check.isChecked()
        s.ocr.tesseract_cmd = self._tesseract_cmd_edit.text().strip()
        s.ocr.device_id_pattern = self._device_pattern_edit.text().strip()

        s.uploads.max_concurrent = self._concurrency_spin.value()
        s.uploads.retry_count = self._retry_count_spin.value()
        s.uploads.retry_backoff_seconds = self._retry_backoff_spin.value()
        s.uploads.chunk_size_mb = self._chunk_size_spin.value()
        s.uploads.duplicate_check = self._dedup_check.isChecked()

        s.save()
        QMessageBox.information(
            self,
            "Settings saved",
            "Settings were saved. Folder, OCR, and concurrency changes take effect the next "
            "time the pipeline starts (restart the app or toggle it from the tray icon).",
        )

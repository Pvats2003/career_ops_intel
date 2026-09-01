"""First-run setup wizard: 8 steps, each validated (against the real
services — a real folder-permission check, a real Drive/Sheets API call,
a real OCR status check, a real tiny test upload) before the user can
continue, so "Finish" means the configuration genuinely works rather than
just being present.

Every validated step (3-7) also has a de-emphasized "Skip for now" option
— this never traps a user who's missing one piece (no Google Sheet yet,
Tesseract not installed yet) in a wizard they can't get past. Anything
skipped is still visible later: unauthenticated shows "Sign-in required"
in the top bar, a missing OCR engine shows on the Health Check page, etc.

Wired up from `app.py`: shown once, before `MainWindow`, when
`SettingsRepository` has no `onboarding_complete` flag set yet. Also
reachable again from Settings (a "Run Setup Wizard Again" button) for
anyone who skipped steps and wants to finish them later.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from instacore_sync.core.config import AppSettings
from instacore_sync.domain.enums import GoogleAuthStatus, HealthStatus
from instacore_sync.domain.models import HealthCheckResult
from instacore_sync.workers.pipeline_thread import PipelineThread
from instacore_sync.workers.signals import PipelineSignalBus

(
    PAGE_WHATSAPP_FOLDER,
    PAGE_PROCESSED_FOLDER,
    PAGE_GOOGLE_AUTH,
    PAGE_DRIVE_FOLDER,
    PAGE_SHEET,
    PAGE_OCR,
    PAGE_UPLOAD,
    PAGE_READY,
) = range(8)


def _folder_picker_row(parent: QWidget, line_edit: QLineEdit, title: str) -> QWidget:
    container = QWidget(parent)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    browse = QPushButton("Browse…")

    def _browse() -> None:
        chosen = QFileDialog.getExistingDirectory(container, title, line_edit.text())
        if chosen:
            line_edit.setText(chosen)

    browse.clicked.connect(_browse)
    layout.addWidget(line_edit, stretch=1)
    layout.addWidget(browse)
    return container


class _FolderPage(QWizardPage):
    """Shared logic for the WhatsApp-folder and Processed-folder steps:
    pick a directory, confirm it exists (or can be created) and is
    writable — no network involved, so validation is synchronous."""

    def __init__(self, title: str, subtitle: str, field_name: str, initial: str) -> None:
        super().__init__()
        self.setTitle(title)
        self.setSubTitle(subtitle)

        layout = QVBoxLayout(self)
        self._edit = QLineEdit(initial)
        self._edit.textChanged.connect(self.completeChanged)
        layout.addWidget(_folder_picker_row(self, self._edit, title))

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #FF8FA3;")
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        self.registerField(field_name, self._edit)

    def folder_text(self) -> str:
        return self._edit.text().strip()

    def isComplete(self) -> bool:  # noqa: N802
        text = self.folder_text()
        if not text:
            return False
        try:
            Path(text).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._error_label.setText(f"Can't use this folder: {exc}")
            return False
        import os

        if not os.access(text, os.W_OK):
            self._error_label.setText("This folder exists but isn't writable.")
            return False
        self._error_label.setText("")
        return True


class WhatsAppFolderPage(_FolderPage):
    def __init__(self, initial: str) -> None:
        super().__init__(
            "Welcome to InstaCore Sync",
            "Step 1 of 8 — Where does WhatsApp Desktop save downloaded videos? This is usually "
            "a folder like Downloads, or WhatsApp's own Media folder.",
            "watch_folder",
            initial,
        )


class ProcessedFolderPage(_FolderPage):
    def __init__(self, initial: str, watch_folder_page: WhatsAppFolderPage) -> None:
        super().__init__(
            "Processed Folder",
            "Step 2 of 8 — Where should InstaCore Sync move videos after they're successfully "
            "uploaded? Pick a folder separate from your WhatsApp folder.",
            "processed_folder",
            initial,
        )
        self._watch_folder_page = watch_folder_page

    def isComplete(self) -> bool:  # noqa: N802
        if not super().isComplete():
            return False
        if Path(self.folder_text()) == Path(self._watch_folder_page.folder_text()):
            self._error_label.setText("This must be different from your WhatsApp folder.")
            return False
        return True


class _AsyncCheckPage(QWizardPage):
    """Shared logic for every step that validates against a real service
    (Google sign-in, Drive, Sheets, OCR, a test upload): a primary action
    button that kicks off the check via `pipeline_thread`, a result label
    fed by `PipelineSignalBus`, and an optional "Skip for now" escape
    hatch so no single missing piece can trap the user in the wizard.
    """

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        action_label: str,
        check_name: str,
        signal_bus: PipelineSignalBus,
        pipeline_thread: PipelineThread,
        allow_skip: bool = True,
    ) -> None:
        super().__init__()
        self.setTitle(title)
        self.setSubTitle(subtitle)
        self._check_name = check_name
        self._pipeline_thread = pipeline_thread
        self._passed = False
        self._skipped = False

        layout = QVBoxLayout(self)
        self.extra_widgets_layout = QVBoxLayout()
        layout.addLayout(self.extra_widgets_layout)

        self._action_button = QPushButton(action_label)
        self._action_button.setObjectName("PrimaryButton")
        self._action_button.clicked.connect(self._on_action_clicked)
        layout.addWidget(self._action_button)

        self._result_label = QLabel("Not checked yet.")
        self._result_label.setWordWrap(True)
        layout.addWidget(self._result_label)

        self._fix_label = QLabel("")
        self._fix_label.setWordWrap(True)
        self._fix_label.setStyleSheet("color: #FBBF24;")
        layout.addWidget(self._fix_label)

        if allow_skip:
            self._skip_check = QCheckBox("Skip for now — I'll set this up later")
            self._skip_check.stateChanged.connect(self._on_skip_toggled)
            layout.addWidget(self._skip_check)
        else:
            self._skip_check = None

        layout.addStretch(1)
        signal_bus.wizard_check_result.connect(self._on_check_result)

    def _on_skip_toggled(self, _state: int) -> None:
        self._skipped = self._skip_check.isChecked() if self._skip_check else False
        self._action_button.setEnabled(not self._skipped)
        self.completeChanged.emit()

    def _on_action_clicked(self) -> None:
        self._action_button.setEnabled(False)
        self._action_button.setText("Checking…")
        self._result_label.setText("Checking…")
        self._fix_label.setText("")
        self.run_check()

    def run_check(self) -> None:  # pragma: no cover - overridden per page
        raise NotImplementedError

    def _on_check_result(self, check_name: str, result: HealthCheckResult) -> None:
        if check_name != self._check_name:
            return
        self._action_button.setEnabled(True)
        self._action_button.setText("Re-check")
        self._passed = result.status == HealthStatus.PASS
        icon = "✅" if self._passed else ("⚠️" if result.status == HealthStatus.WARNING else "❌")
        self._result_label.setText(f"{icon} {result.message}")
        self._fix_label.setText(result.suggested_fix or "")
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self._passed or self._skipped

    @property
    def passed(self) -> bool:
        return self._passed


class GoogleAuthPage(_AsyncCheckPage):
    def __init__(self, signal_bus: PipelineSignalBus, pipeline_thread: PipelineThread) -> None:
        super().__init__(
            title="Sign in to Google",
            subtitle="Step 3 of 8 — InstaCore Sync needs access to Google Drive (to upload videos) "
            "and Google Sheets (to log them). This opens a browser window.",
            action_label="Sign in with Google…",
            check_name="__auth__",  # not used; auth status comes from a different signal
            signal_bus=signal_bus,
            pipeline_thread=pipeline_thread,
            allow_skip=True,
        )
        signal_bus.auth_status_changed.connect(self._on_auth_status)

    def run_check(self) -> None:
        self._pipeline_thread.sign_in_interactively()

    def _on_auth_status(self, status: GoogleAuthStatus, account_email: str | None) -> None:
        self._action_button.setEnabled(True)
        self._action_button.setText("Sign in with Google…")
        if status == GoogleAuthStatus.AUTHENTICATED:
            self._passed = True
            self._result_label.setText(f"✅ Signed in as {account_email or 'your Google account'}")
        elif status == GoogleAuthStatus.AUTHENTICATING:
            self._result_label.setText("Waiting for you to finish signing in in your browser…")
            return
        else:
            self._passed = False
            self._result_label.setText(f"Status: {status.value}")
        self.completeChanged.emit()


class DriveFolderPage(_AsyncCheckPage):
    def __init__(
        self, initial_folder_id: str, signal_bus: PipelineSignalBus, pipeline_thread: PipelineThread
    ) -> None:
        super().__init__(
            title="Google Drive Destination",
            subtitle="Step 4 of 8 — Paste the ID of the Drive folder videos should be uploaded "
            "into. Open the folder in Drive and copy the ID from its web address "
            "(drive.google.com/drive/folders/<this part>).",
            action_label="Verify Folder",
            check_name="drive_folder",
            signal_bus=signal_bus,
            pipeline_thread=pipeline_thread,
            allow_skip=True,
        )
        self._folder_edit = QLineEdit(initial_folder_id)
        self._folder_edit.textChanged.connect(self._on_text_changed)
        self.extra_widgets_layout.addWidget(self._folder_edit)
        self.registerField("drive_root_folder_id", self._folder_edit)

    def _on_text_changed(self, _text: str) -> None:
        self._passed = False
        self._result_label.setText("Not checked yet.")
        self.completeChanged.emit()

    def run_check(self) -> None:
        self._pipeline_thread.verify_drive_folder(self._folder_edit.text().strip())

    def folder_id(self) -> str:
        return self._folder_edit.text().strip()


class SheetPage(_AsyncCheckPage):
    def __init__(
        self, initial_spreadsheet_id: str, signal_bus: PipelineSignalBus, pipeline_thread: PipelineThread
    ) -> None:
        super().__init__(
            title="Google Sheets Log (optional)",
            subtitle="Step 5 of 8 — Paste the ID of the Google Sheet to log every upload to "
            "(from its web address). This is optional — skip it if you don't need a log.",
            action_label="Verify Sheet",
            check_name="spreadsheet",
            signal_bus=signal_bus,
            pipeline_thread=pipeline_thread,
            allow_skip=True,
        )
        self._sheet_edit = QLineEdit(initial_spreadsheet_id)
        self._sheet_edit.textChanged.connect(self._on_text_changed)
        self.extra_widgets_layout.addWidget(self._sheet_edit)
        self.registerField("spreadsheet_id", self._sheet_edit)

    def _on_text_changed(self, _text: str) -> None:
        self._passed = False
        self._result_label.setText("Not checked yet.")
        self.completeChanged.emit()

    def run_check(self) -> None:
        self._pipeline_thread.verify_spreadsheet(self._sheet_edit.text().strip())

    def spreadsheet_id(self) -> str:
        return self._sheet_edit.text().strip()


class OcrTestPage(_AsyncCheckPage):
    def __init__(self, signal_bus: PipelineSignalBus, pipeline_thread: PipelineThread) -> None:
        super().__init__(
            title="Test OCR",
            subtitle="Step 6 of 8 — Confirms the OCR engine that reads Device IDs off your "
            "videos is installed and working.",
            action_label="Test OCR",
            check_name="ocr",
            signal_bus=signal_bus,
            pipeline_thread=pipeline_thread,
            allow_skip=True,
        )

    def run_check(self) -> None:
        self._pipeline_thread.test_ocr()


class UploadTestPage(_AsyncCheckPage):
    def __init__(
        self, drive_folder_page: DriveFolderPage, signal_bus: PipelineSignalBus, pipeline_thread: PipelineThread
    ) -> None:
        super().__init__(
            title="Test Upload",
            subtitle="Step 7 of 8 — Uploads a small test file to your configured Drive folder "
            "and deletes it right away, to confirm everything actually works end to end.",
            action_label="Test Upload",
            check_name="upload",
            signal_bus=signal_bus,
            pipeline_thread=pipeline_thread,
            allow_skip=True,
        )
        self._drive_folder_page = drive_folder_page

    def initializePage(self) -> None:  # noqa: N802
        if not self._drive_folder_page.folder_id():
            self._result_label.setText("No Drive folder was configured in the previous step — skip this too.")
            self._action_button.setEnabled(False)

    def run_check(self) -> None:
        self._pipeline_thread.test_upload(self._drive_folder_page.folder_id())


class ReadyPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Ready")
        self.setSubTitle("Step 8 of 8 — Here's what was configured. You can change any of this "
                          "later in Settings.")
        layout = QVBoxLayout(self)
        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        layout.addWidget(self._summary)

    def set_summary(self, text: str) -> None:
        self._summary.setPlainText(text)


class FirstRunWizard(QWizard):
    def __init__(
        self,
        settings: AppSettings,
        signal_bus: PipelineSignalBus,
        pipeline_thread: PipelineThread,
        app_icon: QIcon | None = None,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("InstaCore Sync Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(700, 520)
        if app_icon is not None:
            self.setWindowIcon(app_icon)

        self._watch_page = WhatsAppFolderPage(settings.watch_folder)
        self._processed_page = ProcessedFolderPage(settings.processed_folder, self._watch_page)
        self._auth_page = GoogleAuthPage(signal_bus, pipeline_thread)
        self._drive_page = DriveFolderPage(settings.drive.root_folder_id, signal_bus, pipeline_thread)
        self._sheet_page = SheetPage(settings.sheets.spreadsheet_id, signal_bus, pipeline_thread)
        self._ocr_page = OcrTestPage(signal_bus, pipeline_thread)
        self._upload_page = UploadTestPage(self._drive_page, signal_bus, pipeline_thread)
        self._ready_page = ReadyPage()

        for page_id, page in (
            (PAGE_WHATSAPP_FOLDER, self._watch_page),
            (PAGE_PROCESSED_FOLDER, self._processed_page),
            (PAGE_GOOGLE_AUTH, self._auth_page),
            (PAGE_DRIVE_FOLDER, self._drive_page),
            (PAGE_SHEET, self._sheet_page),
            (PAGE_OCR, self._ocr_page),
            (PAGE_UPLOAD, self._upload_page),
            (PAGE_READY, self._ready_page),
        ):
            self.setPage(page_id, page)

        self.currentIdChanged.connect(self._on_page_changed)

    def _on_page_changed(self, page_id: int) -> None:
        if page_id == PAGE_READY:
            self._ready_page.set_summary(self._build_summary())

    def _build_summary(self) -> str:
        lines = [
            f"WhatsApp folder: {self._watch_page.folder_text()}",
            f"Processed folder: {self._processed_page.folder_text()}",
            f"Google sign-in: {'done' if self._auth_page.passed else 'skipped'}",
            f"Drive folder: {self._drive_page.folder_id() or '(skipped)'}",
            f"Google Sheet: {self._sheet_page.spreadsheet_id() or '(skipped)'}",
            f"OCR: {'verified' if self._ocr_page.passed else 'skipped — set up Tesseract later'}",
            f"Test upload: {'succeeded' if self._upload_page.passed else 'skipped'}",
            "",
            "Click Finish to save this configuration and start using InstaCore Sync.",
        ]
        return "\n".join(lines)

    def apply_to_settings(self) -> None:
        """Called by the caller after `exec()` returns Accepted — writes
        every collected value into the live `AppSettings` object (the
        same instance the rest of the app already holds a reference to,
        same pattern as `AppSettings.update_from`) and persists it."""
        s = self._settings
        s.watch_folder = self._watch_page.folder_text()
        s.processed_folder = self._processed_page.folder_text()
        s.drive.root_folder_id = self._drive_page.folder_id()
        s.sheets.spreadsheet_id = self._sheet_page.spreadsheet_id()
        for folder in (s.processed_folder, s.needs_review_folder, s.failed_folder):
            if folder:
                Path(folder).mkdir(parents=True, exist_ok=True)
        s.save()

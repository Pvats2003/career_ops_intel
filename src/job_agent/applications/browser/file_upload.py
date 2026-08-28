"""Phase 6D Stage 1 — `FileUploadHandler`: one narrow method, attaches
exactly one file to exactly one declared upload field. Never a generic
"upload anything anywhere" method — the field id and the local file path
are both required, explicit arguments every time."""

from __future__ import annotations

from pathlib import Path

from job_agent.applications.browser.session import BrowserSession


class FileUploadHandler:
    def attach_resume(self, session: BrowserSession, field_id: str, resume_path: Path) -> None:
        if not resume_path.exists():
            raise FileNotFoundError(f"resume file not found: {resume_path}")
        session.set_input_files(f'[data-field="{field_id}"]', resume_path)

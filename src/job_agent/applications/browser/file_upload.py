"""Phase 6D Stage 1 — `FileUploadHandler`: one narrow method, attaches
exactly one file to exactly one declared upload field. Never a generic
"upload anything anywhere" method — the field id and the local file path
are both required, explicit arguments every time.

Phase 6D password-field fix: this method is only ever called (in every
real code path in this repository) with a field the inspector already
classified as `input_type == "file"` — see `providers/browser_application.
py`'s `fill_application`. If it is ever called with a field id that does
not resolve to an upload-capable control, the underlying Playwright
error is never re-raised as-is: Playwright's own exception message can
embed the matched element's outerHTML (e.g. a password field's live
`value` attribute), which this class must never surface."""

from __future__ import annotations

from pathlib import Path

from job_agent.applications.browser.inspector import field_selector
from job_agent.applications.browser.session import BrowserSession


class FileUploadHandler:
    def attach_resume(self, session: BrowserSession, field_id: str, resume_path: Path) -> None:
        if not resume_path.exists():
            raise FileNotFoundError(f"resume file not found: {resume_path}")
        try:
            session.set_input_files(field_selector(field_id), resume_path)
        except Exception:
            # Deliberately not `raise ... from exc`: the original
            # exception's message is exactly what must not propagate.
            raise RuntimeError(
                f"failed to attach resume to field {field_id!r}: target element does "
                "not accept a file upload"
            ) from None

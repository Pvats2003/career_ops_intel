from __future__ import annotations

from typing import Any


class ResumeExtractionError(ValueError):
    """Raised when the authoritative resume file cannot be read.

    BUILD PROMPT section 45/9's "never silently guess" principle applies
    here just as much as to the markdown parser: a missing, corrupted, or
    empty resume file must stop the pipeline with a clear error, never fall
    back to treating the candidate/*.md files as unverified.
    """


class ResumeConsistencyError(ValueError):
    """Raised when a candidate profile contains a claim that cannot be
    traced back to the authoritative resume file.

    This is the hallucination/invention guard required by the Phase 4 spec:
    every fact in the parsed CandidateProfile must be verifiable against
    resume_master.docx, or the system must say so explicitly rather than
    silently versioning an unverified profile.
    """

    def __init__(self, issues: list[Any]) -> None:
        self.issues = issues
        detail = "; ".join(f"[{i.field}] {i.detail}" for i in issues)
        super().__init__(f"{len(issues)} unverifiable claim(s) against resume: {detail}")

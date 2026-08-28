"""BrowserApplicationProvider — Phase 6D Stage 1: "Prepare + Human Submit".

============================================================================
SUBMISSION IS STRUCTURALLY UNAVAILABLE IN THIS PHASE.
`submit()` unconditionally raises `SubmissionRefusedError` — no flag, no
constructor argument, no configuration, and no code path anywhere in this
class reaches a real click on a real submit control. This mirrors
`job_agent.applications.providers.structured_ats.StructuredATSProvider`'s
proven Phase 6B pattern exactly: the same "no hidden path such as
dry_run=false -> provider.submit()" guarantee, satisfied structurally,
never by a runtime guard that could later be removed.
============================================================================
WHAT THIS PROVIDER DOES: discovers a LOCAL target (a caller-supplied
`job_id -> URL` mapping — in this phase, always a URL this repository's
own test suite serves on 127.0.0.1), opens a narrow, single-origin
`job_agent.applications.browser.session.BrowserSession` against it,
inspects the live DOM for structural facts (fields, CAPTCHA, MFA,
consent) via `ApplicationFormInspector`, maps visible fields to the
existing `ApplicationQuestion` type via `DynamicFieldMapper`, and — when
`fill_application()` is called with already-generated, already-validated
answers from the existing, unmodified `job_agent.applications.
answer_engine` pipeline — fills the DOM via the narrow, named-method-only
`FormFiller`, then builds a `HumanReviewSnapshot` from a FRESH
re-inspection of the resulting DOM state (never from what the filler
merely thinks it set).

WHAT THIS PROVIDER NEVER DOES:
- Never attempts, solves, or evades a CAPTCHA/MFA challenge. Detection is
  passive DOM inspection only; the resulting `ApplicationInspection`
  facts flow through the SAME, unmodified
  `job_agent.applications.rules_enforcement.evaluate_inspection` routing
  every other inspecting provider already uses — this class adds no new
  gate logic.
- Never follows a redirect or navigation off its bound origin —
  `BrowserSession` hard-stops via `DomainDriftDetectedError` instead.
- Never guesses at a field with no pre-generated answer (including one
  revealed only after filling began) — it is recorded as unresolved in
  the snapshot, never filled.
- Never decides whether it is ALLOWED to submit — `requires_persisted_
  approval = True` means the existing Phase 6C gate in
  `job_agent.applications.service.submit_application` would apply if this
  provider's `submit()` ever did anything, exactly as it already does for
  `RealStructuredATSProvider`. Moot today, since `submit()` always
  refuses regardless of gate state — but set for documentation honesty
  and forward consistency, not because it changes anything yet.

STAGE 1 STATUS: nothing in this repository or its test suite constructs
this provider against any URL other than a local synthetic HTTP server
the test suite itself serves. No credential of any kind is used, read, or
referenced anywhere in this file.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from job_agent.applications.browser.answer_planner import AnswerPlanner
from job_agent.applications.browser.field_mapper import DynamicFieldMapper
from job_agent.applications.browser.file_upload import FileUploadHandler
from job_agent.applications.browser.filler import FormFiller
from job_agent.applications.browser.inspector import ApplicationFormInspector
from job_agent.applications.browser.session import BrowserSession
from job_agent.applications.browser.snapshot import (
    CAPTCHA_OR_MFA_AFTER_FILL_MARKER,
    HumanReviewSnapshot,
    UploadedFileRecord,
    build_snapshot,
)
from job_agent.applications.errors import SubmissionRefusedError
from job_agent.applications.provider import ApplicationProvider, ProviderHealthCheck
from job_agent.applications.schema import (
    ApplicationInspection,
    ApplicationQuestion,
    ApplicationTarget,
    GeneratedAnswer,
    PreparedFormState,
    QuestionCategory,
    SubmissionEvidence,
    VerificationResult,
)
from job_agent.db.models import Job as JobRow

if TYPE_CHECKING:
    from playwright.sync_api import Browser

# Representative fallback, mirroring every other provider's own — used
# only when no local target URL is registered for a job at all (so
# get_questions() still degrades honestly rather than returning nothing).
_FALLBACK_QUESTIONS: tuple[ApplicationQuestion, ...] = (
    ApplicationQuestion(text="Tell me about yourself.", category=QuestionCategory.MOTIVATION),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BrowserApplicationProvider(ApplicationProvider):
    """Phase 6D Stage 1's first browser-automation provider. See module
    docstring for the full safety boundary."""

    name = "browser_application"
    supports_inspection = True
    requires_persisted_approval = True

    def __init__(
        self,
        target_urls: Mapping[int, str],
        *,
        browser: Browser,
        resume_path: Path | None = None,
    ) -> None:
        self._target_urls: dict[int, str] = dict(target_urls)
        self._browser = browser
        self._resume_path = resume_path
        self._last_snapshot: dict[int, HumanReviewSnapshot] = {}

    def get_snapshot(self, job_id: int) -> HumanReviewSnapshot | None:
        """Provider-specific accessor, not part of the `ApplicationProvider`
        ABC — the rich `HumanReviewSnapshot` is this provider's own
        internal record, kept separate from the generic, minimal
        `PreparedFormState` every provider returns from `fill_application`
        so the shared cross-provider schema needs no change for this."""
        return self._last_snapshot.get(job_id)

    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        target_url = self._target_urls.get(job.id)
        if target_url is None:
            return list(_FALLBACK_QUESTIONS)
        with BrowserSession(target_url, browser=self._browser) as session:
            session.load()
            inspection = ApplicationFormInspector().inspect(session)
            return DynamicFieldMapper().to_questions(inspection)

    def submit(self, job: JobRow, answers: list[GeneratedAnswer]) -> SubmissionEvidence:
        # Unconditional refusal — no branch, no flag, no answers-dependent
        # path reaches anything resembling a real submission. See module
        # docstring's SUBMISSION IS STRUCTURALLY UNAVAILABLE section.
        raise SubmissionRefusedError(
            f"BrowserApplicationProvider has no real submission capability for job {job.id} "
            f"({job.company_name} — {job.title}). Automated submission is structurally "
            "unavailable in this phase; a human must review the prepared snapshot and "
            "submit manually."
        )

    def verify(self, job: JobRow, evidence: SubmissionEvidence) -> VerificationResult:
        return VerificationResult(
            verified=False,
            evidence=None,
            reason=(
                "BrowserApplicationProvider has no real submission integration; nothing "
                "was ever actually submitted, so no evidence can be verified."
            ),
        )

    def health_check(self) -> ProviderHealthCheck:
        return ProviderHealthCheck(
            healthy=True,
            detail=(
                f"browser_application: {len(self._target_urls)} local target(s) "
                "registered; submission structurally disabled"
            ),
            checked_at=datetime.now(UTC),
        )

    def discover_application(self, job: JobRow) -> ApplicationTarget:
        target_url = self._target_urls.get(job.id)
        if target_url is None:
            return ApplicationTarget(
                job_id=job.id,
                reachable=False,
                detail=f"no local target URL registered for job {job.id}",
            )
        return ApplicationTarget(
            job_id=job.id,
            reachable=True,
            provider_reference=target_url,
            detail=f"local target registered for job {job.id}",
        )

    def inspect_application(
        self, job: JobRow, target: ApplicationTarget
    ) -> ApplicationInspection:
        if not target.reachable or not target.provider_reference:
            return ApplicationInspection(
                structure_recognized=False,
                detail="no discovered target to inspect",
            )
        with BrowserSession(target.provider_reference, browser=self._browser) as session:
            session.load()
            snap = ApplicationFormInspector().inspect(session)
        visible = [f for f in snap.fields if f.visible]
        structure_recognized = (
            bool(visible) and not snap.captcha_detected and not snap.mfa_detected
        )
        return ApplicationInspection(
            structure_recognized=structure_recognized,
            captcha_detected=snap.captcha_detected,
            mfa_detected=snap.mfa_detected,
            consent_required=bool(snap.consent_fields),
            detail=f"inspected {len(visible)} visible field(s) on the live DOM",
        )

    def retrieve_application_questions(
        self, job: JobRow, target: ApplicationTarget
    ) -> list[ApplicationQuestion]:
        return self.get_questions(job)

    def fill_application(
        self, job: JobRow, target: ApplicationTarget, answers: list[GeneratedAnswer]
    ) -> PreparedFormState:
        target_url = target.provider_reference or self._target_urls.get(job.id)
        if not target.reachable or not target_url:
            return PreparedFormState(
                target_job_id=job.id,
                answer_count=len(answers),
                detail="no reachable target; nothing staged",
            )

        with BrowserSession(target_url, browser=self._browser) as session:
            session.load()
            inspection = ApplicationFormInspector().inspect(session)
            visible = tuple(f for f in inspection.fields if f.visible)

            plans = AnswerPlanner().plan(visible, answers)
            filler = FormFiller(session)
            fill_result = filler.apply_plan(plans)

            uploaded_files: tuple[UploadedFileRecord, ...] = ()
            resume_field = next((f for f in visible if f.input_type == "file"), None)
            if resume_field is not None and self._resume_path is not None:
                FileUploadHandler().attach_resume(
                    session, resume_field.field_id, self._resume_path
                )
                uploaded_files = (
                    UploadedFileRecord(
                        field_id=resume_field.field_id,
                        filename=self._resume_path.name,
                        sha256=_sha256_file(self._resume_path),
                    ),
                )

            unresolved = list(fill_result.unresolved_field_ids)
            unresolved += fill_result.newly_revealed_field_ids

            # Defensive re-check: if a CAPTCHA/MFA marker appeared only
            # AFTER filling began (never present at the initial
            # inspect_application() call that gated entry to this
            # method), that is exactly the kind of anomaly a human must
            # see, not something the snapshot should silently look clean
            # about — never re-attempt to satisfy it, just surface it.
            post_fill_inspection = ApplicationFormInspector().inspect(session)
            if post_fill_inspection.captcha_detected or post_fill_inspection.mfa_detected:
                unresolved.append(CAPTCHA_OR_MFA_AFTER_FILL_MARKER)

            snapshot = build_snapshot(
                session,
                job_id=job.id,
                company_name=job.company_name,
                title=job.title,
                uploaded_files=uploaded_files,
                unresolved_field_ids=tuple(unresolved),
            )
            self._last_snapshot[job.id] = snapshot

        return PreparedFormState(
            target_job_id=job.id,
            answer_count=len(fill_result.filled_field_ids),
            provider_reference=target_url,
            detail=(
                f"staged {len(fill_result.filled_field_ids)} field(s) locally; "
                f"{len(unresolved)} unresolved question(s) remain. Nothing was "
                "transmitted anywhere — a human must review the snapshot "
                "(BrowserApplicationProvider.get_snapshot) and submit manually; "
                "automated submission is structurally unavailable in this phase."
            ),
        )

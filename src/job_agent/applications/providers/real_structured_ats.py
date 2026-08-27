"""RealStructuredATSProvider — Phase 6C's first genuinely submission-capable
`ApplicationProvider`.

============================================================================
THIS MODULE IS NOT DORMANT. Unlike `job_agent.security.credentials`'s
`NullCredentialStore` or `job_agent.applications.verification_contract`,
`submit()`/`verify()` here CAN make a real network call and CAN produce
genuine `SubmissionEvidence` — if constructed with a credential provider
that resolves a real secret and pointed at a job whose `application_url`
is a real platform endpoint. Every other layer in this phase (the
`requires_persisted_approval` gate in `job_agent.applications.service`,
the exact-posting allowlist, single-use fingerprint-bound approvals) exists
specifically because THIS module is where real capability first appears.
============================================================================
STAGE 1 STATUS (see the Phase 6C approval this module was built under):
nothing in this repository or its test suite constructs this provider with
a real credential or points it at a real platform URL. Every test exercises
it with a synthetic `EnvCredentialStore`-or-fake `CredentialProvider` reading
a fake environment variable, and an `httpx.MockTransport`-backed HTTP
client — never a real network call. Selecting one real posting and wiring
a real credential is Stage 2, requiring its own separate, explicit human
approval; nothing here performs that wiring on its own.
============================================================================

WHAT THIS PROVIDER DOES:

- `discover_application`/`inspect_application`/`get_questions`/
  `fill_application`: local-fixture-only, exactly mirroring
  `job_agent.applications.providers.structured_ats.StructuredATSProvider`'s
  Phase 6B pattern — no network call, caller-supplied
  `RealATSSubmissionConfig` mapping, honest conservative defaults when no
  config is registered for a job.
- `submit`: resolves a credential from an injected `CredentialProvider`
  (never reads `os.environ` itself — that stays inside
  `job_agent.security.credentials`), then makes exactly ONE POST (via
  `job_agent.applications.submission_http.SubmissionHttpClient`, bound to
  `job.application_url` — the exact URL a human approved via the Phase 6C
  allowlist before `job_agent.applications.service.submit_application`
  ever calls this method) carrying the validated answers. Refuses to
  fabricate evidence: a 2xx response with no extractable
  `confirmation_id` in the JSON body raises
  `SubmissionOutcomeUnknownError`, never a guessed `SubmissionEvidence`.
- `verify`: makes a SEPARATE, independent POST — to a distinct
  `verification_url` from the same config, never the submission URL again
  — that re-asks the platform to confirm the exact `confirmation_id`
  `submit()` returned. This is deliberately not "trust `evidence` because
  it looks well-formed" (that is only what
  `job_agent.applications.verification_contract.validate_submission_evidence`
  checks, and its own docstring says shape-validity is not proof); a
  mismatched or missing confirmation on the independent re-check means
  `verified=False`, even if the original `SubmissionEvidence` object looks
  perfectly plausible.

WHAT THIS PROVIDER NEVER DOES:

- Never decides whether it is ALLOWED to submit — `requires_persisted_approval
  = True` means `job_agent.applications.service.submit_application` refuses
  to call `submit()` at all without a valid, unexpired, unconsumed,
  fingerprint-matching `ApplicationApproval` plus a matching allowlist
  entry. This provider has no knowledge of approvals, allowlists,
  automation level, or rate limits — exactly the same "provider reports
  facts/results, core decides consequences" boundary every prior-phase
  provider observes (see `job_agent.applications.provider`'s module
  docstring).
- Never retries a POST internally — `SubmissionHttpClient.post()` makes
  exactly one attempt; an ambiguous failure propagates to the caller as
  `SubmissionOutcomeUnknownError` untouched, for
  `job_agent.applications.service.submit_application` to route to
  `SUBMISSION_UNCERTAIN`.
- Never hardcodes a real ATS platform name, hostname, or API shape. Every
  URL this provider ever contacts comes from caller-supplied configuration
  (`RealATSSubmissionConfig.verification_url`) or from the `Job` row
  itself (`job.application_url`) — never a literal in this file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from job_agent.applications.errors import (
    ProviderError,
    ProviderTimeoutError,
    SubmissionOutcomeUnknownError,
    SubmissionRefusedError,
)
from job_agent.applications.provider import ApplicationProvider, ProviderHealthCheck
from job_agent.applications.providers.structured_ats import ATSFieldType, ATSFormField
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
from job_agent.applications.submission_http import SubmissionHttpClient
from job_agent.db.models import Job as JobRow
from job_agent.security.credentials import (
    CredentialProvider,
    CredentialUnavailableError,
    EnvCredentialStore,
)

_SUPPORTED_FIELD_TYPES = frozenset(t.value for t in ATSFieldType)

# Representative fallback, mirroring StructuredATSProvider's own —
# deliberately a separate, small tuple rather than a cross-module import of
# another provider's private constant (see structured_ats.py's own
# docstring for the same reasoning).
_FALLBACK_QUESTIONS: tuple[ApplicationQuestion, ...] = (
    ApplicationQuestion(text="Tell me about yourself.", category=QuestionCategory.MOTIVATION),
    ApplicationQuestion(text="Why do you want to work here?", category=QuestionCategory.COMPANY),
    ApplicationQuestion(
        text="Why are you a good fit for this role?", category=QuestionCategory.ROLE
    ),
    ApplicationQuestion(
        text="Will you now or in the future require visa sponsorship?",
        category=QuestionCategory.VISA,
    ),
    ApplicationQuestion(
        text="What are your salary expectations?", category=QuestionCategory.SALARY
    ),
    ApplicationQuestion(
        text="When are you available to start?", category=QuestionCategory.AVAILABILITY
    ),
)


class RealATSSubmissionConfig(BaseModel):
    """Local/fixture configuration for one job's real-submission target.

    `verification_url` is deliberately a SEPARATE endpoint from
    `job.application_url` (the submission target) — `verify()` must make
    an independent request, never just re-confirm against the same
    endpoint `submit()` already used. Never fetched or guessed; a caller
    (test, or a future explicitly-reviewed Stage 2 wiring) supplies it.
    """

    model_config = ConfigDict(frozen=True)

    verification_url: str
    ats_application_id: str = ""
    captcha_present: bool = False
    mfa_present: bool = False
    consent_required: bool = False
    fields: tuple[ATSFormField, ...] = Field(default_factory=tuple)


class _RealFixtureFormEntry(BaseModel):
    """One entry of a local fixture file (see `load_real_fixture_forms`) —
    keyed by `application_url`, mirroring `job_agent.applications.
    providers.structured_ats._FixtureFormEntry`'s exact reasoning: a Job
    row's database id doesn't exist until the job has actually been
    scanned/persisted, so it can't be known ahead of time in a static
    config file."""

    model_config = ConfigDict(frozen=True)

    application_url: str
    verification_url: str
    ats_application_id: str = ""
    captcha_present: bool = False
    mfa_present: bool = False
    consent_required: bool = False
    fields: tuple[ATSFormField, ...] = Field(default_factory=tuple)


class _RealFixtureFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    forms: tuple[_RealFixtureFormEntry, ...] = Field(default_factory=tuple)


def load_real_fixture_forms(path: Path) -> dict[str, RealATSSubmissionConfig]:
    """Reads a LOCAL fixture YAML file and returns a mapping of
    `application_url -> RealATSSubmissionConfig`. A single local file read
    — `yaml.safe_load` — and nothing else; no network call. Mirrors
    `job_agent.applications.providers.structured_ats.load_fixture_forms`
    exactly, including its failure modes: a missing file raises
    `FileNotFoundError` (never a silent empty mapping that would route
    every job to HUMAN_REQUIRED for a confusing reason), and a duplicate
    `application_url` raises `ValueError` (never a silent last-wins pick).
    """
    if not path.exists():
        raise FileNotFoundError(f"real_structured_ats fixture file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    parsed = _RealFixtureFile.model_validate(raw)

    forms: dict[str, RealATSSubmissionConfig] = {}
    for entry in parsed.forms:
        if entry.application_url in forms:
            raise ValueError(
                "real_structured_ats fixture file has duplicate application_url entries: "
                f"{entry.application_url!r}"
            )
        forms[entry.application_url] = RealATSSubmissionConfig(
            verification_url=entry.verification_url,
            ats_application_id=entry.ats_application_id,
            captcha_present=entry.captcha_present,
            mfa_present=entry.mfa_present,
            consent_required=entry.consent_required,
            fields=entry.fields,
        )
    return forms


def _structure_recognized(config: RealATSSubmissionConfig) -> bool:
    if not config.fields:
        return False
    return all(field.field_type in _SUPPORTED_FIELD_TYPES for field in config.fields)


def _question_text(field: ATSFormField) -> str:
    parts = [field.label]
    if field.placeholder:
        parts.append(f"(placeholder: {field.placeholder})")
    if field.description:
        parts.append(f"(description: {field.description})")
    if field.options:
        parts.append(f"(options: {', '.join(field.options)})")
    return " ".join(parts)


def _to_question(field: ATSFormField) -> ApplicationQuestion:
    from job_agent.applications.answer_engine import classify_question

    text = _question_text(field)
    return ApplicationQuestion(
        text=text, category=classify_question(text), required=field.required
    )


class RealStructuredATSProvider(ApplicationProvider):
    """Phase 6C's first real, submission-capable `ApplicationProvider`. See
    module docstring for the full safety boundary."""

    name = "real_structured_ats"
    supports_inspection = True
    requires_persisted_approval = True

    def __init__(
        self,
        forms: Mapping[int, RealATSSubmissionConfig],
        credential_provider: CredentialProvider,
        credential_name: str,
    ) -> None:
        self._forms: dict[int, RealATSSubmissionConfig] = dict(forms)
        self._credential_provider = credential_provider
        self._credential_name = credential_name

    @classmethod
    def from_env_credential(
        cls,
        forms: Mapping[int, RealATSSubmissionConfig],
        credential_name: str,
        credential_env_var: str,
    ) -> RealStructuredATSProvider:
        """Convenience constructor for `job_agent.applications.service.
        build_application_provider`, so THAT module never needs to import
        `job_agent.security.credentials` directly — this file stays the
        one, explicitly-reviewed consumer of that module outside itself
        (see `tests/unit/test_credentials.py::TestDormancy`). Constructs
        an `EnvCredentialStore` bound to `credential_env_var` — reads
        nothing until `submit`/`verify`/`health_check` actually calls
        `get_credential`, and even then only from the process
        environment, never a config file or a hardcoded value."""
        return cls(forms, EnvCredentialStore(credential_name, credential_env_var), credential_name)

    def _resolve_credential(self) -> str:
        return self._credential_provider.get_credential(self._credential_name)

    def get_questions(self, job: JobRow) -> list[ApplicationQuestion]:
        config = self._forms.get(job.id)
        if config is None:
            return list(_FALLBACK_QUESTIONS)
        return [_to_question(field) for field in config.fields]

    def submit(self, job: JobRow, answers: list[GeneratedAnswer]) -> SubmissionEvidence:
        if any(answer.requires_human for answer in answers):
            raise SubmissionRefusedError(
                f"job {job.id}: one or more answers still require human review; "
                "refusing to submit until every answer is resolved."
            )
        if not job.application_url:
            raise SubmissionRefusedError(
                f"job {job.id}: no application_url is set on this job; refusing to submit "
                "with no submission target."
            )
        try:
            credential = self._resolve_credential()
        except CredentialUnavailableError as exc:
            raise SubmissionRefusedError(
                f"job {job.id}: no credential available for real submission "
                f"({self._credential_name!r} is not configured): {exc}"
            ) from exc

        config = self._forms.get(job.id)
        payload = {
            "job_id": job.id,
            "ats_application_id": config.ats_application_id if config else "",
            "answers": [
                {"question": answer.question, "answer": answer.answer} for answer in answers
            ],
        }
        client = SubmissionHttpClient(job.application_url)
        try:
            response = client.post(payload, headers={"Authorization": f"Bearer {credential}"})
        finally:
            client.close()

        # Any response in this range means the round trip completed and the
        # platform explicitly declined the request — a definite outcome,
        # never ambiguous (see submission_http.py's module docstring).
        if not (200 <= response.status_code < 300):
            raise SubmissionRefusedError(
                f"job {job.id}: submission endpoint rejected the request "
                f"(HTTP {response.status_code}): {response.text[:500]}"
            )

        try:
            body = json.loads(response.text)
        except ValueError as exc:
            raise SubmissionOutcomeUnknownError(
                f"job {job.id}: submission endpoint returned HTTP {response.status_code} "
                "but the response body was not valid JSON; cannot produce trustworthy "
                f"evidence of a genuine submission: {exc}"
            ) from exc

        confirmation_id = str(body.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise SubmissionOutcomeUnknownError(
                f"job {job.id}: submission endpoint returned HTTP {response.status_code} "
                "but no confirmation_id was present in the response body; refusing to "
                "fabricate evidence of a genuine submission."
            )

        return SubmissionEvidence(
            confirmation_id=confirmation_id,
            confirmation_url=job.application_url,
            submitted_at=datetime.now(UTC),
        )

    def verify(self, job: JobRow, evidence: SubmissionEvidence) -> VerificationResult:
        config = self._forms.get(job.id)
        if config is None:
            return VerificationResult(
                verified=False, evidence=None,
                reason=f"no submission config registered for job {job.id}; cannot verify.",
            )
        confirmation_id = (evidence.confirmation_id or "").strip()
        if not confirmation_id:
            return VerificationResult(
                verified=False, evidence=None,
                reason="submitted evidence carries no confirmation_id to independently verify.",
            )
        try:
            credential = self._resolve_credential()
        except CredentialUnavailableError as exc:
            return VerificationResult(
                verified=False, evidence=None,
                reason=f"cannot verify without a configured credential: {exc}",
            )

        client = SubmissionHttpClient(config.verification_url)
        try:
            response = client.post(
                {"confirmation_id": confirmation_id},
                headers={"Authorization": f"Bearer {credential}"},
            )
        except (ProviderTimeoutError, ProviderError, SubmissionOutcomeUnknownError) as exc:
            return VerificationResult(
                verified=False, evidence=None,
                reason=f"independent verification request could not be completed: {exc}",
            )
        finally:
            client.close()

        if response.status_code != 200:
            return VerificationResult(
                verified=False, evidence=None,
                reason=(
                    f"verification endpoint returned HTTP {response.status_code}; "
                    "not confirmed."
                ),
            )
        try:
            body = json.loads(response.text)
        except ValueError:
            return VerificationResult(
                verified=False, evidence=None,
                reason="verification endpoint response was not valid JSON; not confirmed.",
            )

        returned_id = str(body.get("confirmation_id") or "").strip()
        status_field = str(body.get("status") or "").strip().lower()
        if returned_id != confirmation_id or status_field != "received":
            return VerificationResult(
                verified=False, evidence=None,
                reason=(
                    "independent verification did not confirm this submission "
                    f"(returned confirmation_id={returned_id!r}, status={status_field!r})"
                ),
            )
        return VerificationResult(
            verified=True, evidence=evidence,
            reason="independently confirmed via a separate verification request.",
        )

    def health_check(self) -> ProviderHealthCheck:
        try:
            self._resolve_credential()
            credential_status = "configured"
        except CredentialUnavailableError:
            credential_status = "not configured"
        return ProviderHealthCheck(
            healthy=True,
            detail=(
                f"real_structured_ats: {len(self._forms)} local fixture config(s) "
                f"registered, credential {credential_status}; health_check itself makes "
                "no network call"
            ),
            checked_at=datetime.now(UTC),
        )

    def discover_application(self, job: JobRow) -> ApplicationTarget:
        config = self._forms.get(job.id)
        if config is None:
            return ApplicationTarget(
                job_id=job.id,
                reachable=False,
                detail=f"no real-submission fixture config registered for job {job.id}",
            )
        return ApplicationTarget(
            job_id=job.id,
            reachable=True,
            provider_reference=config.ats_application_id or None,
            detail=f"real-submission fixture config found for job {job.id}",
        )

    def inspect_application(
        self, job: JobRow, target: ApplicationTarget
    ) -> ApplicationInspection:
        config = self._forms.get(job.id)
        if config is None or not target.reachable:
            return ApplicationInspection(
                structure_recognized=False,
                detail="no discovered real-submission target to inspect",
            )
        return ApplicationInspection(
            structure_recognized=_structure_recognized(config),
            captcha_detected=config.captcha_present,
            mfa_detected=config.mfa_present,
            consent_required=config.consent_required,
            detail=f"inspected {len(config.fields)} field(s) on the local fixture config",
        )

    def fill_application(
        self, job: JobRow, target: ApplicationTarget, answers: list[GeneratedAnswer]
    ) -> PreparedFormState:
        config = self._forms.get(job.id)
        return PreparedFormState(
            target_job_id=job.id,
            answer_count=len(answers),
            provider_reference=config.ats_application_id if config else None,
            detail=(
                "RealStructuredATSProvider stages answers locally only — nothing is "
                "transmitted until submit() is explicitly called through the Phase 6C "
                "approval gate."
            ),
        )

"""Phase 6D Stage 1 — `HumanReviewSnapshot`: the exact final state a human
must review and approve before any future submission could ever be
attempted. Built from a FRESH re-inspection of the live DOM after
filling completes — never from a separately-tracked approximation of
what the filler thinks it set. If the DOM disagrees with what was
planned, the snapshot reflects the DOM, because the DOM is what a real
platform would actually receive.

`compute_snapshot_fingerprint()` mirrors `job_agent.applications.
approvals.compute_answer_fingerprint`'s exact pattern (sha256 over a
sorted, deterministic serialization) — a future stage would bind an
`ApplicationApproval` to this fingerprint the same way it's already
bound to the answer fingerprint today, so any change to the underlying
form's structure after approval is detected the identical way stale
answers already are.

SENSITIVE FIELDS (Phase 6D password-field fix) — this project has no
reviewed, supported mechanism for handling credentials: no login
automation, no credential loading, no OAuth. A discovered
`<input type="password">` (see `inspector.py`'s `_resolve_input_type`)
is therefore never treated as an ordinary answerable field:
`DynamicFieldMapper`/`AnswerPlanner` exclude it from ever becoming a
question or a fill plan, so `FormFiller` has no code path that could
write into one. Here, at the snapshot boundary, the guarantee is
structural rather than a redaction pass over an already-read value:
`_current_value()` returns `PASSWORD_FIELD_REDACTED_PLACEHOLDER`
immediately for a password field, before any DOM query is made for
it — no real value is ever read into this process for that field, so
there is nothing for `HumanReviewSnapshot`, its CLI rendering, or any
downstream consumer to leak. `build_snapshot()` additionally always
places a password field's id in `unresolved_field_ids`, regardless of
what its caller passed in, so it can never be silently presented as a
normal, resolved application question.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from job_agent.applications.browser.inspector import (
    ApplicationFormInspector,
    DiscoveredField,
    field_selector,
)
from job_agent.applications.browser.session import BrowserSession

# A special sentinel that may appear inside HumanReviewSnapshot.
# unresolved_field_ids (never as a real field_id — field ids come from
# DOM attributes, never from this literal) — set by
# BrowserApplicationProvider.fill_application() when a CAPTCHA/MFA
# challenge appears only AFTER filling began (never present at the
# original inspect_application() call that gated entry to filling in the
# first place). Public and defined here, once, so nothing importing it
# (the provider that sets it, the CLI renderer that must recognize and
# surface it distinctly rather than as an ordinary unresolved field) can
# drift out of sync with a second, private copy of the same string.
CAPTCHA_OR_MFA_AFTER_FILL_MARKER = "__captcha_or_mfa_appeared_after_fill__"

# The ONLY string a password-classified field's `SnapshotField.
# current_value` may ever hold. This is a structural guarantee, not a
# redaction pass over a value already read: `_current_value()` returns
# this constant for a password field WITHOUT ever calling into the DOM
# for it (no `.input_value()` call happens at all), so there is no
# "real value" in memory at any point in this module for that field to
# leak from. Public so tests and any future consumer can assert against
# it by name instead of a literal string.
PASSWORD_FIELD_REDACTED_PLACEHOLDER = "[sensitive — password field: never read or filled]"


class UploadedFileRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_id: str
    filename: str
    sha256: str


class SnapshotField(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_id: str
    label: str
    field_type: str
    required: bool
    current_value: str
    # Provenance for a RESOLVED field's current_value -- e.g.
    # "candidate_fact:contact_email", "answer_bank:strengths",
    # "llm:claude-...". Empty string for a field with no associated
    # answer (never filled, or the value came from something other than
    # the answer-resolution pipeline, e.g. a pre-existing DOM value).
    # This is the SAME GeneratedAnswer.source string already computed
    # by the existing, unmodified answer engine -- not a new provenance
    # system, just carrying an existing fact through to the review layer.
    source: str = ""


class HumanReviewSnapshot(BaseModel):
    """See module docstring. Every field here is populated from a live
    DOM read at snapshot-build time — nothing is carried over from an
    earlier planning stage without being re-observed."""

    model_config = ConfigDict(frozen=True)

    job_id: int
    company_name: str
    title: str
    application_url: str
    fields: tuple[SnapshotField, ...] = Field(default_factory=tuple)
    uploaded_files: tuple[UploadedFileRecord, ...] = Field(default_factory=tuple)
    consent_selections: dict[str, bool] = Field(default_factory=dict)
    required_field_ids: tuple[str, ...] = Field(default_factory=tuple)
    optional_field_ids: tuple[str, ...] = Field(default_factory=tuple)
    unresolved_field_ids: tuple[str, ...] = Field(default_factory=tuple)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compute_snapshot_fingerprint(snapshot: HumanReviewSnapshot) -> str:
    parts = [
        f"job_id={snapshot.job_id}",
        f"application_url={snapshot.application_url}",
    ]
    parts += sorted(
        f"field:{f.field_id}={f.field_type}:{f.required}:{f.current_value}"
        for f in snapshot.fields
    )
    parts += sorted(
        f"file:{u.field_id}={u.filename}:{u.sha256}" for u in snapshot.uploaded_files
    )
    parts += sorted(f"consent:{k}={v}" for k, v in snapshot.consent_selections.items())
    parts += sorted(f"unresolved:{fid}" for fid in snapshot.unresolved_field_ids)
    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _current_value(session: BrowserSession, f: DiscoveredField) -> str:
    if f.input_type == "password":
        # Structural, not a redaction pass: return BEFORE any DOM query
        # is made for this field, so no real value is ever read into
        # this process for a password field, let alone displayed. Every
        # other branch below queries the live DOM; this one never does.
        return PASSWORD_FIELD_REDACTED_PLACEHOLDER
    selector = field_selector(f.field_id)
    if f.input_type in ("text", "textarea"):
        el = session.query_all(selector)
        return el[0].input_value() if el else ""
    if f.input_type in ("select", "multiselect"):
        el = session.query_all(selector)
        if not el:
            return ""
        return el[0].evaluate(
            "e => Array.from(e.selectedOptions).map(o => o.textContent).join(', ')"
        )
    if f.input_type == "radio":
        checked = session.query_all(
            f'input[type="radio"]:checked:is([data-field="{f.field_id}"], [name="{f.field_id}"])'
        )
        return checked[0].get_attribute("value") or "" if checked else ""
    if f.input_type == "checkbox":
        el = session.query_all(selector)
        return "true" if el and el[0].is_checked() else "false"
    if f.input_type == "file":
        el = session.query_all(selector)
        if not el:
            return ""
        return el[0].evaluate("e => e.files.length > 0 ? e.files[0].name : ''")
    return ""


def build_snapshot(
    session: BrowserSession,
    *,
    job_id: int,
    company_name: str,
    title: str,
    uploaded_files: tuple[UploadedFileRecord, ...] = (),
    unresolved_field_ids: tuple[str, ...] = (),
    answer_sources: Mapping[str, str] | None = None,
) -> HumanReviewSnapshot:
    """Re-inspects the live DOM (never a cached plan) and assembles the
    final snapshot from what's actually there right now.

    `answer_sources` (field_id -> GeneratedAnswer.source) is a plain
    pass-through of provenance the caller's answer-resolution pipeline
    already computed -- this function does not invent, infer, or alter
    any of it. A field with no entry (never filled, or the caller passed
    none) gets an empty `source`; that is the honest, non-fabricating
    default, never a guessed label."""
    inspector = ApplicationFormInspector()
    inspection = inspector.inspect(session)
    sources: Mapping[str, str] = answer_sources or {}

    fields: list[SnapshotField] = []
    consent_selections: dict[str, bool] = {}
    required_ids: list[str] = []
    optional_ids: list[str] = []
    sensitive_ids: list[str] = []
    for f in inspection.fields:
        if not f.visible or f.input_type == "file":
            continue
        value = _current_value(session, f)
        fields.append(
            SnapshotField(
                field_id=f.field_id,
                label=f.label,
                field_type=f.input_type,
                required=f.required,
                current_value=value,
                source=sources.get(f.field_id, ""),
            )
        )
        if f.is_consent:
            consent_selections[f.field_id] = value == "true"
        if f.input_type == "password":
            # Always unresolved, regardless of what the caller passed in
            # for `unresolved_field_ids` — a password field is never
            # eligible for automated filling (see inspector.py's module
            # docstring), so this can never depend on FormFiller/
            # AnswerPlanner having correctly excluded it upstream.
            sensitive_ids.append(f.field_id)
        if f.required:
            required_ids.append(f.field_id)
        else:
            optional_ids.append(f.field_id)

    all_unresolved = tuple(dict.fromkeys((*unresolved_field_ids, *sensitive_ids)))

    return HumanReviewSnapshot(
        job_id=job_id,
        company_name=company_name,
        title=title,
        application_url=session.target_url,
        fields=tuple(fields),
        uploaded_files=uploaded_files,
        consent_selections=consent_selections,
        required_field_ids=tuple(required_ids),
        optional_field_ids=tuple(optional_ids),
        unresolved_field_ids=all_unresolved,
        captured_at=datetime.now(UTC),
    )

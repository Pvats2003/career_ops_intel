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
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from job_agent.applications.browser.inspector import ApplicationFormInspector, DiscoveredField
from job_agent.applications.browser.session import BrowserSession


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
    selector = f'[data-field="{f.field_id}"]'
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
        checked = session.query_all(f'input[type="radio"][data-field="{f.field_id}"]:checked')
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
) -> HumanReviewSnapshot:
    """Re-inspects the live DOM (never a cached plan) and assembles the
    final snapshot from what's actually there right now."""
    inspector = ApplicationFormInspector()
    inspection = inspector.inspect(session)

    fields: list[SnapshotField] = []
    consent_selections: dict[str, bool] = {}
    required_ids: list[str] = []
    optional_ids: list[str] = []
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
            )
        )
        if f.is_consent:
            consent_selections[f.field_id] = value == "true"
        if f.required:
            required_ids.append(f.field_id)
        else:
            optional_ids.append(f.field_id)

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
        unresolved_field_ids=unresolved_field_ids,
        captured_at=datetime.now(UTC),
    )

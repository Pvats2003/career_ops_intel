"""Phase 6D Stage 2 — renders a `HumanReviewSnapshot` for a human to
actually read, via the CLI. Pure functions only: no browser, no DOM
access, no network, no database — everything here operates on a
`HumanReviewSnapshot` object already built elsewhere
(`job_agent.applications.browser.snapshot.build_snapshot`). Deliberately
free of any `rich`/CLI dependency at the data-shaping layer
(`snapshot_sections`) so it can be unit-tested without a terminal or a
`Console`; `render_snapshot` is the thin `rich`-rendering layer CLI code
actually calls.

Every value shown here already lives on `HumanReviewSnapshot` — this
module adds no new data, no inference, no fabrication. Its only job is
presentation: sorting fields into a stable, deterministic order, and
clearly separating what the system PROPOSED (filled in) from what still
NEEDS a human (unresolved, or a safety condition that appeared after
filling began). `HumanReviewSnapshot` carries no credential of any kind
(see `job_agent.applications.security` boundary this whole package
respects), so nothing here needs its own redaction pass — but this
module still deliberately reads only the documented `HumanReviewSnapshot`
fields, never anything else a caller might be tempted to pass in (e.g. a
live `BrowserSession`), so it can never accidentally surface browser/
session internals a human reviewing this output has no reason to see.

A password field's `current_value` is always `job_agent.applications.
browser.snapshot.PASSWORD_FIELD_REDACTED_PLACEHOLDER` (never a real
value — see that module's docstring), and this renderer never puts it
in the "proposed value" table at all: `build_snapshot()` always marks a
password field unresolved, so it only ever appears in the "needs your
input" list below, which shows only its label, never `current_value`.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

from job_agent.applications.browser.snapshot import (
    CAPTCHA_OR_MFA_AFTER_FILL_MARKER,
    HumanReviewSnapshot,
    SnapshotField,
    compute_snapshot_fingerprint,
)
from job_agent.applications.human_input import HUMAN_INPUT_SOURCE_PREFIX


@dataclass(frozen=True)
class SnapshotSections:
    """Plain-data shaping of a `HumanReviewSnapshot` for display —
    deterministically ordered, with proposed/unresolved/safety-warning
    fields already separated out. No `rich` dependency, so this is
    directly assertable in a unit test."""

    proposed_fields: tuple[SnapshotField, ...]
    unresolved_field_ids: tuple[str, ...]
    safety_warning: str | None
    consent_selections: tuple[tuple[str, bool], ...]
    fingerprint: str
    unattached_optional_files: tuple[SnapshotField, ...]


# Sources that mean "this question was actually resolved with a value" --
# used by `_unresolved_reason_label` below to detect a field AnswerPlanner
# vetoed for a STRUCTURAL reason (e.g. multiselect, which FormFiller has
# no branch for) despite having a real answer, so it is never mislabeled
# with a "resolved" looking badge while sitting in "Needs your input".
_RESOLVED_LOOKING_SOURCE_PREFIXES = (
    "candidate_fact:", "answer_bank:", "llm:", HUMAN_INPUT_SOURCE_PREFIX,
)


def _source_label(source: str) -> str:
    """Human-readable rendering of a SnapshotField's raw provenance
    string (the same `GeneratedAnswer.source` the answer engine already
    computed) -- a display mapping only, never a second classification
    system. An unrecognized/empty source is shown honestly as unknown,
    never guessed at."""
    if source.startswith("candidate_fact:"):
        return "[green]✓ Trusted candidate fact[/green]"
    if source.startswith(HUMAN_INPUT_SOURCE_PREFIX):
        return "[green]✓ Human input[/green]"
    if source.startswith("answer_bank:"):
        return "[green]✓ Answer bank[/green]"
    if source.startswith("llm:"):
        return "[cyan]✓ LLM-generated (validated)[/cyan]"
    if source.startswith("hard_block:") or source.startswith("no_trusted_fact:"):
        return "[yellow]? Human decision required[/yellow]"
    if not source:
        return "[dim](n/a)[/dim]"
    return f"[dim]{source}[/dim]"


def _unresolved_reason_label(field: SnapshotField) -> str:
    """Reason label for a field that IS in `unresolved_field_ids` --
    distinct from `_source_label` above (which assumes the field was
    successfully resolved). A field can be unresolved despite having a
    "resolved-looking" source (candidate_fact:/answer_bank:/llm:/
    human_input:) when AnswerPlanner vetoed it for a reason unrelated to
    the answer itself (currently: multiselect, which FormFiller has no
    fill branch for) -- that case is labeled UNSUPPORTED, never with the
    misleading resolved-looking badge. Every other case falls back to
    `_source_label`'s existing "Human decision required"/unknown mapping."""
    if field.source.startswith(_RESOLVED_LOOKING_SOURCE_PREFIXES):
        return "[magenta]⊘ Unsupported — cannot be filled automatically[/magenta]"
    return _source_label(field.source)


def snapshot_sections(snapshot: HumanReviewSnapshot) -> SnapshotSections:
    """Deterministic ordering: fields sorted by field_id (not DOM
    discovery order, which is an implementation detail of a given page
    load and not something a reviewer should have to depend on)."""
    unresolved = set(snapshot.unresolved_field_ids)
    safety_warning = (
        "A CAPTCHA or MFA challenge appeared only AFTER filling began — this was not "
        "present when the form was first inspected. Never re-attempted automatically; "
        "review the live page yourself before doing anything else."
        if CAPTCHA_OR_MFA_AFTER_FILL_MARKER in unresolved
        else None
    )
    unresolved_visible = tuple(
        sorted(fid for fid in unresolved if fid != CAPTCHA_OR_MFA_AFTER_FILL_MARKER)
    )
    proposed = tuple(
        sorted(
            (f for f in snapshot.fields if f.field_id not in unresolved),
            key=lambda f: f.field_id,
        )
    )
    consent = tuple(sorted(snapshot.consent_selections.items()))
    return SnapshotSections(
        proposed_fields=proposed,
        unresolved_field_ids=unresolved_visible,
        safety_warning=safety_warning,
        consent_selections=consent,
        fingerprint=compute_snapshot_fingerprint(snapshot),
        unattached_optional_files=snapshot.unattached_optional_files,
    )


def render_snapshot(snapshot: HumanReviewSnapshot, console: Console) -> None:
    """The only function in this module that touches `rich` — a thin
    presentation layer over `snapshot_sections`'s already-shaped data."""
    sections = snapshot_sections(snapshot)

    console.print(
        f"\n[bold]{snapshot.company_name} — {snapshot.title}[/bold] (job id {snapshot.job_id})"
    )
    console.print(f"  Target URL: {snapshot.application_url}")
    console.print(f"  Captured at: {snapshot.captured_at.isoformat()}")
    console.print(f"  Snapshot fingerprint: {sections.fingerprint}")

    if sections.safety_warning:
        console.print(f"\n[red bold]SAFETY WARNING:[/red bold] {sections.safety_warning}")

    table = Table(title="Fields the system discovered and proposed to fill")
    table.add_column("Field")
    table.add_column("Label")
    table.add_column("Type")
    table.add_column("Required")
    table.add_column("Proposed value")
    table.add_column("Source")
    for f in sections.proposed_fields:
        table.add_row(
            f.field_id, f.label, f.field_type,
            "yes" if f.required else "no", f.current_value or "[dim](empty)[/dim]",
            _source_label(f.source),
        )
    console.print(table)

    if sections.unresolved_field_ids:
        console.print("\n[yellow bold]Needs your input — never guessed:[/yellow bold]")
        by_id = {f.field_id: f for f in snapshot.fields}
        for fid in sections.unresolved_field_ids:
            field = by_id.get(fid)
            label = field.label if field else fid
            if field is not None and field.field_type == "password":
                console.print(
                    f"  [yellow]?[/yellow] {fid} — {label} "
                    "[red](sensitive — password field, not supported for automated filling)[/red]"
                )
            elif field is not None and field.source:
                reason = _unresolved_reason_label(field)
                console.print(f"  [yellow]?[/yellow] {fid} — {label} ({reason})")
            else:
                console.print(f"  [yellow]?[/yellow] {fid} — {label}")

    if sections.consent_selections:
        console.print("\n[bold]Consent selections (as currently observed on the page):[/bold]")
        for field_id, selected in sections.consent_selections:
            state = "[green]checked[/green]" if selected else "[red]NOT checked[/red]"
            console.print(f"  {field_id}: {state}")

    if sections.unattached_optional_files:
        console.print("\n[dim bold]Optional, not attached:[/dim bold]")
        for f in sections.unattached_optional_files:
            console.print(f"  {f.field_id} — {f.label} [dim](optional — not attached)[/dim]")

    if snapshot.uploaded_files:
        console.print("\n[bold]Uploaded files:[/bold]")
        for uploaded in snapshot.uploaded_files:
            console.print(f"  {uploaded.field_id}: {uploaded.filename} (sha256 {uploaded.sha256})")

    console.print(
        "\n[dim]Nothing above was ever transmitted anywhere. Automated submission is "
        "structurally unavailable in this phase — a human must review this snapshot and "
        "submit manually on the real site.[/dim]"
    )

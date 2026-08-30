"""Phase 6D Stage 2 — `snapshot_sections`/`render_snapshot` (the CLI-visible
`HumanReviewSnapshot` rendering layer). Pure, offline, no browser and no
network — every test constructs a `HumanReviewSnapshot` by hand.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console

from job_agent.applications.browser.snapshot import (
    HumanReviewSnapshot,
    SnapshotField,
    UploadedFileRecord,
    compute_snapshot_fingerprint,
)
from job_agent.applications.browser.snapshot_render import (
    CAPTCHA_OR_MFA_AFTER_FILL_MARKER,
    render_snapshot,
    snapshot_sections,
)


def _field(field_id: str, value: str = "some value", *, required: bool = True) -> SnapshotField:
    return SnapshotField(
        field_id=field_id, label=field_id.replace("_", " ").title(),
        field_type="text", required=required, current_value=value,
    )


def _snapshot(
    *,
    job_id: int = 1,
    company_name: str = "Acme",
    title: str = "Business Analyst",
    application_url: str = "https://example.test/apply",
    fields: tuple[SnapshotField, ...] = (),
    uploaded_files: tuple[UploadedFileRecord, ...] = (),
    consent_selections: dict[str, bool] | None = None,
    unresolved_field_ids: tuple[str, ...] = (),
    unattached_optional_files: tuple[SnapshotField, ...] = (),
) -> HumanReviewSnapshot:
    return HumanReviewSnapshot(
        job_id=job_id, company_name=company_name, title=title,
        application_url=application_url, fields=fields, uploaded_files=uploaded_files,
        consent_selections=consent_selections or {}, unresolved_field_ids=unresolved_field_ids,
        unattached_optional_files=unattached_optional_files,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ==========================================================================
# snapshot_sections — pure data shaping.
# ==========================================================================
def test_proposed_fields_excludes_unresolved_ones():
    snap = _snapshot(
        fields=(_field("zebra"), _field("apple"), _field("mango")),
        unresolved_field_ids=("mango",),
    )
    sections = snapshot_sections(snap)
    assert [f.field_id for f in sections.proposed_fields] == ["apple", "zebra"]


def test_proposed_fields_are_sorted_by_field_id_regardless_of_insertion_order():
    snap = _snapshot(fields=(_field("charlie"), _field("alpha"), _field("bravo")))
    sections = snapshot_sections(snap)
    assert [f.field_id for f in sections.proposed_fields] == ["alpha", "bravo", "charlie"]


def test_unresolved_field_ids_are_sorted():
    snap = _snapshot(unresolved_field_ids=("zebra", "apple", "mango"))
    sections = snapshot_sections(snap)
    assert sections.unresolved_field_ids == ("apple", "mango", "zebra")


def test_captcha_marker_is_extracted_as_safety_warning_not_a_plain_unresolved_field():
    snap = _snapshot(unresolved_field_ids=("full_name", CAPTCHA_OR_MFA_AFTER_FILL_MARKER))
    sections = snapshot_sections(snap)
    assert sections.unresolved_field_ids == ("full_name",)
    assert sections.safety_warning is not None
    assert "CAPTCHA or MFA" in sections.safety_warning


def test_no_safety_warning_when_marker_absent():
    snap = _snapshot(unresolved_field_ids=("full_name",))
    sections = snapshot_sections(snap)
    assert sections.safety_warning is None


def test_consent_selections_sorted():
    snap = _snapshot(consent_selections={"z_consent": True, "a_consent": False})
    sections = snapshot_sections(snap)
    assert sections.consent_selections == (("a_consent", False), ("z_consent", True))


def test_fingerprint_matches_compute_snapshot_fingerprint():
    snap = _snapshot(fields=(_field("full_name"),))
    sections = snapshot_sections(snap)
    assert sections.fingerprint == compute_snapshot_fingerprint(snap)


def test_ordering_is_deterministic_across_repeated_calls():
    snap = _snapshot(
        fields=(_field("z"), _field("a"), _field("m")),
        unresolved_field_ids=("y", "b"),
    )
    first = snapshot_sections(snap)
    second = snapshot_sections(snap)
    assert first == second


# ==========================================================================
# render_snapshot — the rich-rendering layer, captured as text.
# ==========================================================================
def _rendered_text(snap: HumanReviewSnapshot) -> str:
    console = Console(record=True, width=120)
    render_snapshot(snap, console)
    return console.export_text()


def test_render_includes_job_identity_and_url():
    snap = _snapshot(company_name="Drivetrain", title="Business Analyst", job_id=42)
    text = _rendered_text(snap)
    assert "Drivetrain" in text
    assert "Business Analyst" in text
    assert "job id 42" in text
    assert "https://example.test/apply" in text


def test_render_includes_fingerprint():
    snap = _snapshot(fields=(_field("full_name"),))
    text = _rendered_text(snap)
    assert compute_snapshot_fingerprint(snap) in text


def test_render_shows_proposed_field_values():
    snap = _snapshot(fields=(_field("full_name", "Test Candidate"),))
    text = _rendered_text(snap)
    assert "full_name" in text
    assert "Test Candidate" in text


def test_render_separates_unresolved_fields_under_their_own_heading():
    snap = _snapshot(
        fields=(_field("full_name"),),
        unresolved_field_ids=("current_company",),
    )
    text = _rendered_text(snap)
    assert "Needs your input" in text
    assert "current_company" in text


def test_render_shows_reason_for_an_unresolved_field_with_a_known_source():
    """An unresolved field whose GeneratedAnswer.source survived into the
    snapshot (e.g. "no_trusted_fact:current_company") shows a
    human-readable reason next to it, not just a bare "?" -- a reviewer
    should be able to tell WHY a field needs their input, not just THAT
    it does."""
    field = SnapshotField(
        field_id="current_company", label="Current company", field_type="text",
        required=True, current_value="", source="no_trusted_fact:current_company",
    )
    snap = _snapshot(fields=(field,), unresolved_field_ids=("current_company",))
    text = _rendered_text(snap)
    assert "Human decision required" in text


def test_render_shows_captcha_safety_warning_prominently():
    snap = _snapshot(unresolved_field_ids=(CAPTCHA_OR_MFA_AFTER_FILL_MARKER,))
    text = _rendered_text(snap)
    assert "SAFETY WARNING" in text
    assert CAPTCHA_OR_MFA_AFTER_FILL_MARKER not in text  # never shown as if it were a field


def test_render_shows_consent_state_explicitly_true_and_false():
    snap = _snapshot(consent_selections={"consent": False})
    text = _rendered_text(snap)
    assert "NOT checked" in text

    snap_checked = _snapshot(consent_selections={"consent": True})
    text_checked = _rendered_text(snap_checked)
    assert "checked" in text_checked


def test_render_shows_uploaded_file_hash_not_raw_content():
    snap = _snapshot(
        uploaded_files=(
            UploadedFileRecord(field_id="resume", filename="resume.pdf", sha256="a" * 64),
        )
    )
    text = _rendered_text(snap)
    assert "resume.pdf" in text
    assert "a" * 64 in text


def test_optional_unattached_file_never_counted_as_unresolved():
    """An optional, unattached file field (e.g. an optional resume) must
    be visible to a reviewer, but it is NOT a blocking condition -- it
    must never appear in unresolved_field_ids/proposed_fields, which are
    reserved for fields that actually need a decision."""
    resume_field = SnapshotField(
        field_id="resume", label="Resume/CV", field_type="file",
        required=False, current_value="",
    )
    snap = _snapshot(unattached_optional_files=(resume_field,))
    sections = snapshot_sections(snap)
    assert sections.unattached_optional_files == (resume_field,)
    assert sections.unresolved_field_ids == ()
    assert sections.proposed_fields == ()


def test_render_shows_optional_unattached_file_explicitly():
    resume_field = SnapshotField(
        field_id="resume", label="Resume/CV", field_type="file",
        required=False, current_value="",
    )
    snap = _snapshot(unattached_optional_files=(resume_field,))
    text = _rendered_text(snap)
    assert "Optional, not attached" in text
    assert "Resume/CV" in text
    assert "optional — not attached" in text


def test_fingerprint_changes_when_unattached_optional_files_change():
    resume_field = SnapshotField(
        field_id="resume", label="Resume/CV", field_type="file",
        required=False, current_value="",
    )
    without = _snapshot()
    with_resume = _snapshot(unattached_optional_files=(resume_field,))
    assert compute_snapshot_fingerprint(without) != compute_snapshot_fingerprint(with_resume)


def test_render_never_fabricates_never_claims_submission_happened():
    snap = _snapshot()
    text = _rendered_text(snap)
    assert "structurally unavailable" in text
    assert "Nothing above was ever transmitted" in text


def test_render_output_is_deterministic_across_repeated_calls():
    snap = _snapshot(
        fields=(_field("z"), _field("a")),
        unresolved_field_ids=("b",),
        consent_selections={"c": True},
    )
    assert _rendered_text(snap) == _rendered_text(snap)

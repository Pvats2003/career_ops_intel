"""Phase 6D Stage 1 — `FormFiller`: the only component that actually
writes into the DOM, and only ever from a `FieldPlan` an `AnswerPlanner`
already produced. Its public API is a small set of named, single-purpose
methods (fill a text field, select an option, check a box, reveal a
conditional section) — deliberately NOT a generic `click(selector)`
passthrough, so nothing calling this class could ever pass a
submit-button selector through it even by mistake. There is no code path
from here to a real submission: staging answers and transmitting them
are, and remain, two separately-audited actions — see
`job_agent.applications.provider`'s module docstring for why that
boundary matters project-wide, and `providers/browser_application.py`
for how `submit()` enforces it structurally for this provider.

A field with no planned answer (`FieldPlan.answer is None`) is never
filled — its `field_id` is instead recorded as unresolved and surfaces in
the final `HumanReviewSnapshot`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.applications.browser.answer_planner import FieldPlan
from job_agent.applications.browser.inspector import ApplicationFormInspector, DiscoveredField
from job_agent.applications.browser.session import BrowserSession


@dataclass
class FillResult:
    filled_field_ids: list[str] = field(default_factory=list)
    unresolved_field_ids: list[str] = field(default_factory=list)
    newly_revealed_field_ids: list[str] = field(default_factory=list)


class FormFiller:
    def __init__(self, session: BrowserSession) -> None:
        self._session = session
        self._inspector = ApplicationFormInspector()

    def fill_text_field(self, field_id: str, value: str) -> None:
        self._session.fill_text(f'[data-field="{field_id}"]', value)

    def select_dropdown(self, field_id: str, value: str) -> None:
        self._session.select_option(f'[data-field="{field_id}"]', value)

    def select_radio(self, field_id: str, value: str) -> None:
        self._session.check(f'[data-field="{field_id}"][value="{value}"]')

    def check_checkbox(self, field_id: str) -> None:
        self._session.check(f'[data-field="{field_id}"]')

    def reveal_conditional_section(self, trigger_field_id: str) -> None:
        """Some conditional sections in the synthetic fixture are
        revealed by a dedicated `data-reveals` toggle button rather than
        by the answer selection itself — this method exists so that path
        is a named, narrow action, never a generic click passthrough."""
        self._session.click(f'[data-reveals="{trigger_field_id}"]')

    def apply_plan(self, plans: list[FieldPlan]) -> FillResult:
        result = FillResult()
        known_field_ids = {p.field.field_id for p in plans}
        for plan in plans:
            if plan.answer is None:
                result.unresolved_field_ids.append(plan.field.field_id)
                continue
            self._fill_one(plan)
            result.filled_field_ids.append(plan.field.field_id)

        # Filling an answer can reveal new fields (a conditional section).
        # Re-inspect once, after every planned field has been attempted,
        # and report anything now visible that wasn't part of the
        # original plan — never guessed, never filled, always surfaced.
        snapshot_after = self._inspector.inspect(self._session)
        for f in snapshot_after.fields:
            if f.visible and f.field_id not in known_field_ids and f.input_type != "file":
                result.newly_revealed_field_ids.append(f.field_id)
        return result

    def _fill_one(self, plan: FieldPlan) -> None:
        answer = plan.answer
        assert answer is not None
        f = plan.field
        if f.input_type in ("text", "textarea"):
            self.fill_text_field(f.field_id, answer.answer or "")
        elif f.input_type == "select":
            self.select_dropdown(f.field_id, self._match_option_value(f, answer.answer))
        elif f.input_type == "radio":
            self.select_radio(f.field_id, self._match_option_value(f, answer.answer))
        elif f.input_type == "checkbox":
            truthy = (answer.answer or "").strip().lower() in ("yes", "true", "1")
            if truthy:
                self.check_checkbox(f.field_id)
        # multiselect/file are handled by dedicated callers, not here.

    @staticmethod
    def _match_option_value(f: DiscoveredField, answer_text: str | None) -> str:
        answer_text = (answer_text or "").strip().lower()
        for option in f.options:
            if option.text.strip().lower() == answer_text or option.value == answer_text:
                return option.value
        return f.options[0].value if f.options else ""

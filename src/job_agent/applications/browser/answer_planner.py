"""Phase 6D Stage 1 — `AnswerPlanner`: matches already-generated answers
(produced by the existing, unmodified `job_agent.applications.
answer_engine` pipeline, exactly as every other provider already
receives them via `fill_application(job, target, answers)`) to the
fields currently visible in the DOM.

Deliberately NOT a second answer-generation layer. A field that is
visible right now but has no matching pre-generated answer — either
because it was hidden (behind a conditional) when `get_questions()` ran,
or because its question text drifted — is reported as unresolved, never
guessed, and never answered by calling the LLM/answer engine a second
time outside the normal, already-reviewed pipeline. This is a
deliberately more conservative choice than trying to answer newly
revealed fields live; see this package's provider module docstring for
why.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.applications.browser.field_mapper import question_text
from job_agent.applications.browser.inspector import DiscoveredField
from job_agent.applications.schema import GeneratedAnswer


@dataclass(frozen=True)
class FieldPlan:
    field: DiscoveredField
    answer: GeneratedAnswer | None  # None means unresolved — never filled


class AnswerPlanner:
    def plan(
        self, fields: tuple[DiscoveredField, ...], answers: list[GeneratedAnswer]
    ) -> list[FieldPlan]:
        by_text = {a.question: a for a in answers}
        plans: list[FieldPlan] = []
        for f in fields:
            if f.input_type in ("file", "password"):
                # Password fields are never planned for filling — no
                # FieldPlan is ever produced for one, so FormFiller has no
                # code path that could write into it. See inspector.py's
                # module docstring for the full sensitive-field boundary.
                continue
            answer = by_text.get(question_text(f))
            if answer is not None and answer.requires_human:
                # Never fill a field whose answer explicitly requires a
                # human — the existing answer_engine/hard-block pipeline
                # already decided this one can't be answered truthfully;
                # this planner must not silently override that.
                answer = None
            if f.input_type == "multiselect":
                # FormFiller has no multiselect branch yet (Stage 1 never
                # guesses which of several options a free-text answer
                # implies) — force unresolved rather than let a matched
                # answer silently no-op in _fill_one().
                answer = None
            plans.append(FieldPlan(field=f, answer=answer))
        return plans

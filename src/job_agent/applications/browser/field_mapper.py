"""Phase 6D Stage 1 — `DynamicFieldMapper`: turns the inspector's raw
`DiscoveredField`s into the existing, unchanged `ApplicationQuestion`
type, using the existing, unchanged `job_agent.applications.
answer_engine.classify_question` for categorization — exactly the same
approach `job_agent.applications.providers.structured_ats`'s
`_to_question` already uses. No new classification logic is introduced
here.

Only CURRENTLY VISIBLE fields are ever mapped. A conditionally-hidden
field is invisible until something reveals it — this mapper never
guesses at what might appear later; see `filler.py` for how a
field that becomes visible mid-fill, with no pre-planned answer, is
handled (never guessed, always left unresolved).
"""

from __future__ import annotations

from job_agent.applications.answer_engine import classify_question
from job_agent.applications.browser.inspector import DiscoveredField, InspectionSnapshot
from job_agent.applications.schema import ApplicationQuestion


def question_text(field: DiscoveredField) -> str:
    parts = [field.label]
    if field.options:
        option_text = ", ".join(o.text for o in field.options)
        parts.append(f"(options: {option_text})")
    return " ".join(parts)


def visible_fields(snapshot: InspectionSnapshot) -> tuple[DiscoveredField, ...]:
    return tuple(f for f in snapshot.fields if f.visible)


class DynamicFieldMapper:
    def to_questions(self, snapshot: InspectionSnapshot) -> list[ApplicationQuestion]:
        questions = []
        for f in visible_fields(snapshot):
            if f.input_type == "file":
                continue  # file uploads are handled by FileUploadHandler, not answered as text
            if f.input_type == "password":
                # Never turned into a question: this project has no
                # reviewed mechanism for supplying credentials, and asking
                # the answer engine to answer one risks it inventing a
                # plausible-looking value. See inspector.py's module
                # docstring for the full sensitive-field boundary.
                continue
            text = question_text(f)
            questions.append(
                ApplicationQuestion(
                    text=text, category=classify_question(text), required=f.required
                )
            )
        return questions

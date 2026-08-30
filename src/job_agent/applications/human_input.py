"""Real-target-readiness checkpoint: human-supplied answers at review
time for a question the existing four-tier `answer_engine.generate_answer()`
pipeline correctly left unresolved (`requires_human=True`) — e.g. "Current
company", which has no trusted `CandidateProfile` fact and is never
inferred from experience/employer/LLM (see `answer_engine.py`'s module
docstring).

Deliberately NOT a new resolution tier inside `generate_answer()`, not a
workflow engine, and not a new state-machine: `apply_human_input_overrides`
runs strictly AFTER the full `answers` list already exists, as a one-shot
post-processing pass over already-generated answers. Two consequences of
that ordering are the whole point of this module existing:

* A human's value can NEVER reach the LLM's `CANDIDATE_FACTS` payload —
  the LLM has already finished running (or been skipped) for every
  question by the time this function is ever called; there is no code
  path here that could feed a value back into a prompt.
* This never touches `CandidateProfile` — it produces a NEW, purely
  in-memory `GeneratedAnswer` for this one preparation run only, never a
  write to the candidate's stored facts. Running the exact same
  preparation again without repeating `--answer` returns to
  `requires_human=True`, exactly as before.

Only ever overrides a question that is CURRENTLY unresolved
(`requires_human=True`) — an already-resolved answer (a trusted fact, an
answer-bank hit, a validated LLM draft) is never silently replaced. This
is deliberate: it means a human CAN supply an answer for a hard-block
category (SALARY/VISA/LEGAL/DEMOGRAPHIC) too, which is not a bypass —
`requires_human=True` there means exactly "this needs an explicit
personal/legal decision from the candidate", and a human typing that
decision in at review time is the intended resolution, not an evasion of
it. What it can never do is override a decision the system already made
on its own (a trusted fact it already resolved, or a value the LLM
already drafted and validated).
"""

from __future__ import annotations

from job_agent.applications.schema import GeneratedAnswer

# Prefix convention matches every other GeneratedAnswer.source this system
# already produces (f"candidate_fact:{attr}", f"hard_block:{category}",
# f"answer_bank:{slug}") -- never a bespoke format only this module uses.
HUMAN_INPUT_SOURCE_PREFIX = "human_input:"


def apply_human_input_overrides(
    answers: list[GeneratedAnswer], overrides: dict[str, str]
) -> list[GeneratedAnswer]:
    """`overrides` maps a question's exact text, as it appears on the
    form (e.g. "Current company"), to a human-supplied value. Returns a
    NEW list in the same order — `answers` itself is never mutated, and
    an answer with no matching override, or one that is already
    resolved, is passed through completely unchanged (same object)."""
    if not overrides:
        return answers
    result: list[GeneratedAnswer] = []
    for answer in answers:
        override_value = overrides.get(answer.question)
        if override_value is not None and answer.requires_human:
            result.append(
                GeneratedAnswer(
                    question=answer.question,
                    category=answer.category,
                    answer=override_value,
                    confidence=1.0,
                    source=f"{HUMAN_INPUT_SOURCE_PREFIX}{answer.question}",
                    requires_human=False,
                    validated=True,
                    validation_notes=(),
                )
            )
        else:
            result.append(answer)
    return result

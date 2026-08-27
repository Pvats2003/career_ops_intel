"""Loads the human-authored answer bank (candidate/answers/*.md) that
Phase 1 already established the format for: a `question_type`/
`requires_human` frontmatter block, a `---` separator, then the answer
body (or, when `requires_human: true`, an explanation of why it can't be
pre-written truthfully).

This is the first, cheapest, most-trusted source `answer_engine` tries —
a human already wrote and vetted this content, so it needs no further
fabrication check (see `job_agent.applications.answer_validator`, which
exists for LLM-drafted answers, not these).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from job_agent.applications.schema import QuestionCategory


class AnswerBankParseError(ValueError):
    """A candidate/answers/*.md file doesn't match the expected format."""


@dataclass(frozen=True)
class AnswerBankEntry:
    slug: str
    category: QuestionCategory
    requires_human: bool
    body: str
    source: str


# Maps a bank entry's slug to phrases that identify a matching incoming
# question. Multiple entries can share a QuestionCategory (MOTIVATION has
# three), so category alone isn't enough to pick the right one.
_SLUG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tell_me_about_yourself": ("tell me about yourself", "describe yourself", "introduce yourself"),
    "why_this_company": (
        "why do you want to work", "why this company", "why us",
        "interested in joining", "interested in our company",
    ),
    "why_this_role": (
        "why this role", "why are you interested in this position",
        "good fit for this role", "why are you a good fit",
    ),
    "biggest_achievement": (
        "biggest achievement", "proudest accomplishment", "greatest accomplishment",
    ),
    "leadership": ("leadership experience", "describe a time you led", "led a team"),
    "failure": ("biggest failure", "describe a time you failed", "mistake you made"),
    "strengths": ("greatest strength", "your strengths", "your top strengths"),
    "salary_expectations": (
        "salary expectation", "salary expectations", "compensation expectation",
        "compensation expectations", "expected salary", "expected ctc",
    ),
}


def load_answer_bank(answers_dir: Path) -> list[AnswerBankEntry]:
    entries = []
    for path in sorted(answers_dir.glob("*.md")):
        entries.append(_parse_entry(path))
    return entries


def _parse_entry(path: Path) -> AnswerBankEntry:
    text = path.read_text(encoding="utf-8")
    if "---" not in text:
        raise AnswerBankParseError(f"{path}: missing '---' frontmatter separator")
    frontmatter, _, body = text.partition("---")

    metadata: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        metadata[key.strip().lower()] = value.strip()

    if "question_type" not in metadata:
        raise AnswerBankParseError(f"{path}: missing 'question_type' in frontmatter")
    if "requires_human" not in metadata:
        raise AnswerBankParseError(f"{path}: missing 'requires_human' in frontmatter")

    try:
        category = QuestionCategory(metadata["question_type"].upper())
    except ValueError as exc:
        raise AnswerBankParseError(
            f"{path}: unknown question_type '{metadata['question_type']}'"
        ) from exc

    return AnswerBankEntry(
        slug=path.stem,
        category=category,
        requires_human=metadata["requires_human"].strip().lower() == "true",
        body=body.strip(),
        source=path.stem,
    )


def match_slug(question_text: str) -> str | None:
    """Returns the bank slug whose keywords best match `question_text`, or
    None if nothing matches closely enough to trust."""
    from job_agent.matching.text import contains_keyword

    for slug, keywords in _SLUG_KEYWORDS.items():
        if any(contains_keyword(question_text, kw) for kw in keywords):
            return slug
    return None

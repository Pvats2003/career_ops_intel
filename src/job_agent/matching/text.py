"""Text-matching primitives shared across the deterministic matcher.

Deliberately simple: word-boundary, case-insensitive substring matching.
This is Stage 1/2 of the cost-optimization pipeline (BUILD PROMPT section
40) — cheap, fully explainable, and requires no LLM call. It will produce
false negatives on paraphrased requirements ("comfortable with spreadsheets"
won't match "Excel"); that's an accepted limitation of keyword matching,
not a bug — the semantic stage (section 40 Stage 4) exists specifically to
catch what this stage can't.
"""

from __future__ import annotations

import re

from job_agent.matching.vocabulary import SKILL_SYNONYM_GROUPS


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def contains_keyword(text: str, keyword: str) -> bool:
    """Case-insensitive, word-boundary-aware substring check.

    Handles multi-word keywords (e.g. "product roadmap") and keywords with
    internal punctuation (e.g. "A/B testing", "Figma (basic)") by matching
    on normalized tokens rather than a literal regex word boundary, which
    would mishandle the punctuation.
    """
    if not text or not keyword:
        return False
    haystack = f" {normalize(text)} "
    needle = f" {normalize(keyword)} "
    return needle.strip() != "" and needle in haystack


def any_keyword_present(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [kw for kw in keywords if contains_keyword(text, kw)]


def fuzzy_overlap(a: str, b: str) -> bool:
    """True if either normalized string is a substring of the other.

    For matching a bare vocabulary term ("SQL") against a candidate's
    self-authored skill name ("Basic SQL", "Figma (basic)") — an exact
    phrase match (`contains_keyword`) would treat a job asking for plain
    "SQL" as not matching a skill literally named "Basic SQL", wrongly
    reporting a real, demonstrated skill as missing. Originally written
    once for `matching.deterministic._find_evidence`; factored out here
    (real-world activation audit) after the same "SQL" vs "Basic SQL" gap
    was found independently in `resume.tailor`, which had its own,
    stricter check that missed it — one shared definition instead of two
    that can silently drift apart."""
    if not a or not b:
        return False
    norm_a, norm_b = normalize(a), normalize(b)
    return bool(norm_a) and (norm_a in norm_b or norm_b in norm_a)


def keyword_synonyms(keyword: str) -> frozenset[str]:
    """Every known-safe alternate surface form for `keyword` — always
    includes `keyword` itself. Looks up `job_agent.matching.vocabulary.
    SKILL_SYNONYM_GROUPS`, a small, hand-curated, closed set (see that
    module's docstring for the exact groups and why each member is safe);
    a keyword with no defined synonyms returns just itself, unchanged."""
    normalized_keyword = normalize(keyword)
    for group in SKILL_SYNONYM_GROUPS:
        if normalized_keyword in {normalize(member) for member in group}:
            return frozenset(group) | {keyword}
    return frozenset({keyword})


def contains_keyword_or_synonym(text: str, keyword: str) -> bool:
    """Like `contains_keyword`, but also matches any of `keyword`'s known
    synonym forms (see `keyword_synonyms`) — e.g. a job posting phrased
    "document processes" satisfies the vocabulary term "process
    documentation" without a general fuzzy/stemming relaxation."""
    return any(contains_keyword(text, form) for form in keyword_synonyms(keyword))


def any_keyword_or_synonym_present(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [kw for kw in keywords if contains_keyword_or_synonym(text, kw)]


def fuzzy_overlap_with_synonyms(a: str, b: str) -> bool:
    """Like `fuzzy_overlap`, but also checks `a`'s known synonym forms
    (see `keyword_synonyms`) against `b` — e.g. the vocabulary term
    "product roadmap" recognizes a candidate skill literally named
    "Roadmapping" as the same evidenced skill."""
    return any(fuzzy_overlap(form, b) for form in keyword_synonyms(a))


# Matching Engine V3 calibration fix A: a RANGE ("0-2 years", "1-3 years",
# "2 to 4 years", "2-4+ years") states its LOWER bound as the actual
# requirement — "0-2 years" means 0 years is enough, not that 2 is
# required. The old single pattern only ever looked for a lone number
# immediately followed by "year(s)", so on a range it silently matched
# whichever number happened to sit right before "years" — always the
# UPPER bound — materially over-stating the requirement for exactly the
# phrasing most common in early-career postings. Three alternatives, tried
# in this order at each position: (1) "at least"/"minimum" prefixes and
# (3) the plain/"+"/"or more" forms both resolve to the single number that
# already IS the real lower bound; (2) an explicit range captures only its
# first number. Across MULTIPLE distinct mentions in the same text, the
# largest resolved requirement still wins (the most stringent one stated),
# preserving the original "no specific number found -> None" and "several
# different figures mentioned -> take the most demanding one" behavior —
# only how a SINGLE mention resolves to a number has changed.
_YEAR_REQUIREMENT_PATTERN = re.compile(
    r"(?:at least|minimum(?:\s+of)?)\s*(?P<atleast>\d{1,2})\s*\+?\s*years?\b"
    r"|(?P<range_low>\d{1,2})\s*(?:-|–|to)\s*\d{1,2}\+?\s*years?\b"
    r"|(?P<plain>\d{1,2})\s*(?:\+\s*|or\s+more\s+)?years?\b"
)


def extract_year_requirement(text: str) -> int | None:
    """Extract the largest EFFECTIVE "N years" style requirement mentioned
    (a range's lower bound, an "at least"/"minimum"/"N+"/"N or more"
    figure taken as-is), or None if the text states no explicit years
    requirement at all."""
    if not text:
        return None
    lowered = text.lower()
    candidates: list[int] = []
    for match in _YEAR_REQUIREMENT_PATTERN.finditer(lowered):
        value = match.group("atleast") or match.group("range_low") or match.group("plain")
        year = int(value)
        if year <= 40:  # guard against parsing noise
            candidates.append(year)
    return max(candidates) if candidates else None

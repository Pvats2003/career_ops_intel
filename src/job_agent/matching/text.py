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


def extract_year_requirement(text: str) -> int | None:
    """Extract the largest "N+ years" style requirement mentioned, or None."""
    if not text:
        return None
    matches = re.findall(r"(\d{1,2})\s*\+?\s*year", text.lower())
    years = [int(m) for m in matches if int(m) <= 40]  # guard against parsing noise
    return max(years) if years else None

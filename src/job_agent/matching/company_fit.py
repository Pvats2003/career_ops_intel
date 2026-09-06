"""Company fit score — Career OS Phase 10 section 15.

Derived ENTIRELY from real, already-computed `JobMatch` rows for a
company's postings — never a fabricated "culture fit"/"funding stage"/
"growth trajectory" judgment, since this system has no verified source
for any of that. If none of a company's postings have been matched yet
(no `JobMatch` rows), the fit is genuinely UNKNOWN — this module returns
`None` rather than inventing a neutral placeholder, because a company
detail page is a "should I care about this company" question a candidate
directly reads, and an unearned number there would be misleading in a way
a ranking-formula midpoint (see `job_agent.matching.ranking`) is not.
"""

from __future__ import annotations

from job_agent.db.models import JobMatch as JobMatchRow

_DECISION_WEIGHT: dict[str, float] = {
    "APPLY": 1.0,
    "REVIEW": 0.65,
    "HUMAN_REQUIRED": 0.45,
    "SAVE": 0.3,
    "SKIP": 0.0,
}


def compute_company_fit(matches: list[JobMatchRow]) -> tuple[int | None, tuple[str, ...]]:
    """(fit_score, reasons). `fit_score` is 0-100, or `None` if this
    company has no matched postings yet — role availability, candidate
    interest overlap, and career upside are all read off of the real
    match scores/decisions already computed for THIS company's postings,
    never a second, separate judgment."""
    if not matches:
        return None, ("No matched postings for this company yet — fit not yet computable.",)

    avg_score = sum(m.overall_score for m in matches) / len(matches)
    decision_signal = sum(_DECISION_WEIGHT.get(m.decision, 0.0) for m in matches) / len(matches)
    fit = round(0.7 * avg_score + 0.3 * decision_signal * 100)

    apply_count = sum(1 for m in matches if m.decision == "APPLY")
    reasons = [
        f"Average candidate-fit score across {len(matches)} posting"
        f"{'s' if len(matches) != 1 else ''} at this company: {round(avg_score)}/100.",
    ]
    if apply_count:
        reasons.append(
            f"{apply_count} posting{'s' if apply_count != 1 else ''} at this company reached "
            "an APPLY decision."
        )
    return max(0, min(100, fit)), tuple(reasons)

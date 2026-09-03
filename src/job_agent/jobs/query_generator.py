"""Search query portfolio generation — Career OS Phase 8 section 4.

Generates the set of search terms `job_agent.jobs.service.run_scan` passes
to query-based sources (Remotive/Arbeitnow/Adzuna — see `job_agent.jobs.
sources`) instead of relying on one generic query. Deterministic and
LLM-free by design: query generation gates what gets searched at all, so
it must work identically whether or not `ANTHROPIC_API_KEY` is configured,
and it must never silently drop to zero queries just because the LLM is
unavailable.

Every generated string traces back to something the candidate's own
profile actually states (a target role, a skill, an experience title) —
this module never invents a role the candidate never mentioned wanting or
having evidence for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.candidate.schema import CandidateProfile

# Generic role-noun suffixes used to build "transferable-skill" queries —
# e.g. skill "Automation" + suffix "Analyst" -> "Automation Analyst". Kept
# to a small, deliberately generic set; this is a query BROADENING
# mechanism, not a claim the candidate holds any of these titles.
_ROLE_SUFFIXES: tuple[str, ...] = ("Analyst", "Associate", "Coordinator", "Specialist")

# Skill categories worth turning into their own query terms — "technical"
# and "domain" skills read as job-title-shaped ("Product Operations",
# "Supply Chain"); "soft"/interpersonal skills (e.g. "Communication",
# "Leadership") don't, so they're excluded from title generation.
_TITLE_WORTHY_CATEGORIES = frozenset({"technical", "domain", "tool"})


@dataclass(frozen=True)
class SearchQueryPortfolio:
    """One bucket per BUILD PROMPT section 4 category. `all_queries`
    dedupes and flattens the buckets in priority order (core first) —
    that flattened list is what source adapters actually receive."""

    core_roles: tuple[str, ...] = field(default_factory=tuple)
    adjacent_roles: tuple[str, ...] = field(default_factory=tuple)
    transferable_skill_roles: tuple[str, ...] = field(default_factory=tuple)
    emerging_roles: tuple[str, ...] = field(default_factory=tuple)

    @property
    def all_queries(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for bucket in (
            self.core_roles,
            self.adjacent_roles,
            self.transferable_skill_roles,
            self.emerging_roles,
        ):
            for query in bucket:
                key = query.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    ordered.append(query.strip())
        return tuple(ordered)


def _title_case_dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return tuple(out)


def generate_search_queries(
    profile: CandidateProfile, *, max_transferable: int = 6, max_emerging: int = 4
) -> SearchQueryPortfolio:
    """Build the query portfolio purely from what the profile already
    states — no external calls, no LLM. Safe to call on every search run,
    including with no LLM configured at all."""
    core = _title_case_dedupe(list(profile.target_roles.primary))
    adjacent = _title_case_dedupe(list(profile.target_roles.secondary))

    # Transferable-skill roles: combine each title-worthy skill with a
    # generic role suffix, but only when that skill isn't already covered
    # by a stated target role (avoids "Product Analyst" as a "new"
    # discovery when the candidate already listed it as a primary role).
    stated = {q.lower() for q in (*core, *adjacent)}
    transferable: list[str] = []
    for skill in profile.skills:
        if skill.category not in _TITLE_WORTHY_CATEGORIES:
            continue
        for suffix in _ROLE_SUFFIXES:
            candidate_query = f"{skill.name} {suffix}"
            if candidate_query.lower() in stated:
                continue
            transferable.append(candidate_query)
        if len(transferable) >= max_transferable:
            break
    transferable_deduped = _title_case_dedupe(transferable)[:max_transferable]

    # Emerging roles: the candidate's own "exploratory" target roles, plus
    # actual past experience titles not already represented above — a
    # cheap, honest way to surface "titles this candidate has genuinely
    # held but hasn't flagged as a target" without guessing anything new.
    emerging_pool = list(profile.target_roles.exploratory) + [
        e.title for e in profile.experience
    ]
    emerging = [
        title
        for title in _title_case_dedupe(emerging_pool)
        if title.lower() not in stated
        and title.lower() not in {t.lower() for t in transferable_deduped}
    ][:max_emerging]

    return SearchQueryPortfolio(
        core_roles=core,
        adjacent_roles=adjacent,
        transferable_skill_roles=transferable_deduped,
        emerging_roles=tuple(emerging),
    )

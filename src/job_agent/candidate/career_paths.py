"""Career path discovery — Career OS Phase 8 section 5.

Deterministic by design (like `job_agent.jobs.query_generator`): scores
every path in `_TAXONOMY` against the candidate's own stated target roles,
skills, and experience titles, using the same word-boundary keyword
matching `job_agent.matching.text` already uses for job-requirement
matching. A path only appears in the result if it has at least one piece
of real evidence in the profile — this module never invents a path score
from nothing.

`_TAXONOMY` is a curated reference list of common, real job-market
categories (the kind a career counselor would already have in mind), not
a claim about the candidate — it exists so "missing skills"/"typical job
titles" have something concrete to compare against, the same reason
`job_agent.matching.vocabulary` exists for job-requirement matching. It is
deliberately not exhaustive; extending it does not require touching the
scoring logic below.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.candidate.schema import CandidateProfile
from job_agent.matching.text import contains_keyword


@dataclass(frozen=True)
class _CareerPathDefinition:
    label: str
    typical_titles: tuple[str, ...]
    key_skills: tuple[str, ...]
    upside: str  # "High" | "Medium" | "Emerging" — a general signal, not a personalized prediction


_TAXONOMY: tuple[_CareerPathDefinition, ...] = (
    _CareerPathDefinition(
        "Product Operations",
        ("Product Operations Analyst", "Product Operations Manager", "Product Ops"),
        ("product roadmap", "roadmapping", "KPI", "OKR", "process documentation",
         "stakeholder management", "cross-functional", "SQL", "data analysis"),
        "High",
    ),
    _CareerPathDefinition(
        "Business Operations",
        ("Business Operations Analyst", "Business Operations Associate", "BizOps"),
        ("process documentation", "stakeholder management", "KPI", "Excel",
         "data analysis", "project management", "cross-functional"),
        "Medium",
    ),
    _CareerPathDefinition(
        "Strategy & Operations",
        ("Strategy & Operations Analyst", "Strategy Associate", "Chief of Staff"),
        ("market research", "competitive analysis", "KPI", "OKR", "stakeholder management",
         "data analysis", "process documentation"),
        "Medium",
    ),
    _CareerPathDefinition(
        "AI Operations",
        ("AI Operations Analyst", "AI Product Operations", "ML Operations Analyst"),
        ("machine learning", "artificial intelligence", "LLM", "generative AI", "Python",
         "data analysis", "process documentation"),
        "High",
    ),
    _CareerPathDefinition(
        "Product Management",
        ("Associate Product Manager", "Product Analyst", "Junior Product Manager"),
        ("product roadmap", "roadmapping", "PRD", "user research", "backlog grooming",
         "sprint planning", "A/B testing", "stakeholder management"),
        "High",
    ),
    _CareerPathDefinition(
        "Business Analysis",
        ("Business Analyst", "Technical Business Analyst", "Business Systems Analyst"),
        ("SQL", "data analysis", "stakeholder communication", "process documentation",
         "Excel", "business analysis"),
        "Medium",
    ),
    _CareerPathDefinition(
        "Program / Project Management",
        ("Program Manager", "Project Manager", "Program Analyst"),
        ("Agile", "Scrum", "Kanban", "JIRA", "stakeholder management", "project management",
         "cross-functional"),
        "Medium",
    ),
    _CareerPathDefinition(
        "Data / Analytics",
        ("Data Analyst", "Analytics Associate", "Business Intelligence Analyst"),
        ("SQL", "data analysis", "data analytics", "Tableau", "Power BI", "Looker", "Python", "R"),
        "High",
    ),
    _CareerPathDefinition(
        "UX / Product Design",
        ("UX Analyst", "Product Designer", "UX Researcher"),
        ("Figma", "user research", "usability research", "wireframing", "prototyping"),
        "Medium",
    ),
    _CareerPathDefinition(
        "Software Engineering",
        ("Software Engineer", "Backend Engineer", "Full-Stack Engineer"),
        ("Python", "React", "Node.js", "TypeScript", "API"),
        "High",
    ),
    _CareerPathDefinition(
        "Marketing Operations",
        ("Marketing Operations Analyst", "Growth Operations Analyst"),
        ("market research", "KPI", "data analysis", "process documentation",
         "cross-functional"),
        "Emerging",
    ),
    _CareerPathDefinition(
        "Customer Success Operations",
        ("Customer Success Operations Analyst", "Customer Success Associate"),
        ("stakeholder management", "process documentation", "KPI", "cross-functional"),
        "Emerging",
    ),
)


@dataclass(frozen=True)
class CareerPathResult:
    label: str
    fit_score: int  # 0-100
    evidence: tuple[str, ...]
    relevant_skills: tuple[str, ...]
    relevant_experience: tuple[str, ...]
    missing_skills: tuple[str, ...]
    typical_titles: tuple[str, ...]
    career_upside: str
    recommended_priority: str  # "HIGH" | "MEDIUM" | "LOW"
    source: str = "profile"  # "profile" (taxonomy match) vs "llm" (future extension point)


def _stated_role_texts(profile: CandidateProfile) -> tuple[tuple[str, str], ...]:
    """(role text, weight-bucket) pairs — a role the candidate explicitly
    listed as a PRIMARY target is much stronger evidence than one merely
    inferred from a past job title."""
    out: list[tuple[str, str]] = []
    out += [(r, "primary") for r in profile.target_roles.primary]
    out += [(r, "secondary") for r in profile.target_roles.secondary]
    out += [(r, "exploratory") for r in profile.target_roles.exploratory]
    out += [(e.title, "experience") for e in profile.experience]
    return tuple(out)


def discover_career_paths(
    profile: CandidateProfile, *, max_results: int = 8
) -> list[CareerPathResult]:
    """Deterministic core: score every taxonomy path, keep only paths with
    real evidence, rank by fit, return the top `max_results`."""
    role_texts = _stated_role_texts(profile)
    candidate_skill_names = [s.name for s in profile.skills]

    results: list[CareerPathResult] = []
    for path in _TAXONOMY:
        matched_skills = [
            skill for skill in path.key_skills
            if any(contains_keyword(name, skill) or contains_keyword(skill, name)
                   for name in candidate_skill_names)
        ]
        title_evidence: list[str] = []
        stated_role_bonus = 0
        for role_text, bucket in role_texts:
            if any(contains_keyword(role_text, t) or contains_keyword(t, role_text)
                   for t in (path.label, *path.typical_titles)):
                title_evidence.append(f"{role_text} ({bucket})")
                stated_role_bonus = max(
                    stated_role_bonus,
                    {"primary": 40, "secondary": 25, "exploratory": 15, "experience": 20}[bucket],
                )

        if not matched_skills and not title_evidence:
            continue

        skill_coverage = len(matched_skills) / len(path.key_skills) if path.key_skills else 0.0
        fit_score = min(100, round(skill_coverage * 60) + stated_role_bonus)

        evidence = tuple(
            [f"Skill match: {s}" for s in matched_skills]
            + [f"Stated/held role: {t}" for t in title_evidence]
        )
        missing = tuple(s for s in path.key_skills if s not in matched_skills)

        results.append(
            CareerPathResult(
                label=path.label,
                fit_score=fit_score,
                evidence=evidence,
                relevant_skills=tuple(matched_skills),
                relevant_experience=tuple(title_evidence),
                missing_skills=missing,
                typical_titles=path.typical_titles,
                career_upside=path.upside,
                recommended_priority="LOW",  # set below once ranked
            )
        )

    results.sort(key=lambda r: r.fit_score, reverse=True)
    top = results[:max_results]

    ranked: list[CareerPathResult] = []
    for index, result in enumerate(top):
        priority = "HIGH" if index < 3 else "MEDIUM" if index < 6 else "LOW"
        ranked.append(
            CareerPathResult(
                label=result.label, fit_score=result.fit_score, evidence=result.evidence,
                relevant_skills=result.relevant_skills,
                relevant_experience=result.relevant_experience,
                missing_skills=result.missing_skills, typical_titles=result.typical_titles,
                career_upside=result.career_upside, recommended_priority=priority,
                source=result.source,
            )
        )
    return ranked

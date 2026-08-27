"""A modest, curated vocabulary of requirement keywords typical of
product/business-analyst postings, used by the deterministic skills/project
matcher to decide what to look for in a job's text.

This is NOT an exhaustive skills taxonomy — it exists so the matcher has
*something* concrete to search for beyond the candidate's own skill list
(otherwise no skill could ever be classified MISSING, since we'd never look
for a skill the candidate doesn't have). It is deliberately scoped to the
target role family in config/profile.yaml; extend it if target roles change.
"""

from __future__ import annotations

COMMON_REQUIREMENT_KEYWORDS: tuple[str, ...] = (
    "SQL",
    "Excel",
    "Google Sheets",
    "Agile",
    "Scrum",
    "Kanban",
    "JIRA",
    "Confluence",
    "Tableau",
    "Power BI",
    "Looker",
    "A/B testing",
    "product roadmap",
    "roadmapping",
    "stakeholder management",
    "stakeholder communication",
    "Figma",
    "user research",
    "usability research",
    "wireframing",
    "prototyping",
    "Python",
    "R",
    "data analysis",
    "data analytics",
    "KPI",
    "OKR",
    "market research",
    "competitive analysis",
    "PRD",
    "backlog grooming",
    "sprint planning",
    "MoSCoW",
    "React",
    "Node.js",
    "TypeScript",
    "API",
    "machine learning",
    "artificial intelligence",
    "LLM",
    "generative AI",
    "process documentation",
    "cross-functional",
    "project management",
    "product management",
    "business analysis",
)

SENIOR_KEYWORDS: tuple[str, ...] = (
    "senior",
    "sr.",
    "staff",
    "principal",
    "lead",
    "director",
    "head of",
    "vp",
    "vice president",
    "manager",
)

JUNIOR_KEYWORDS: tuple[str, ...] = (
    "entry level",
    "entry-level",
    "associate",
    "junior",
    "new grad",
    "new graduate",
    "intern",
    "internship",
    "early career",
)

DEGREE_REQUIRED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("phd required", "phd"),
    ("phd degree required", "phd"),
    ("master's degree required", "masters"),
    ("masters degree required", "masters"),
    ("mba required", "mba"),
    ("bachelor's degree required", "bachelors"),
    ("bachelors degree required", "bachelors"),
    ("bachelor's degree is required", "bachelors"),
)

NO_SPONSORSHIP_PATTERNS: tuple[str, ...] = (
    "no visa sponsorship",
    "sponsorship is not available",
    "sponsorship not available",
    "unable to sponsor",
    "not able to sponsor",
    "without sponsorship",
    "must be authorized to work",
    "must be eligible to work",
    "authorized to work in the united states",
    "work authorization required",
)

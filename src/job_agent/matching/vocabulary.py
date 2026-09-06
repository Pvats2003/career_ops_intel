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

# Matching Engine V3 calibration fix C: production-audit finding — a bare
# "manager" used to be in this list, making "Product Manager" (this
# candidate's own, literal, primary target-role title, per
# config/profile.yaml) hard-stop into HUMAN_REQUIRED purely because
# "manager" happens to be a substring of it, even with no seniority
# qualifier at all. Every word below is an explicit, unambiguous seniority
# marker that never doubles as a standard entry-point title for any of
# this candidate's target role families. Compound "<Function> Manager"
# titles that DO still legitimately signal real seniority (Engineering
# Manager, Marketing Manager, ...) are handled separately by
# `FUNCTIONAL_MANAGER_SENIOR_TITLES` below, not by a bare-word match here.
EXPLICIT_SENIORITY_MARKERS: tuple[str, ...] = (
    "senior",
    "sr.",
    "staff",
    "principal",
    "lead",
    "director",
    "head of",
    "vp",
    "vice president",
    "chief",
)

# A small, explicit list of COMPOUND "<Function> Manager" titles that DO
# still legitimately signal real managerial seniority even with no
# separate Senior/Lead/Director qualifier — unlike bare "Manager" or
# "Product Manager", these describe someone managing a team/function, not
# an individual-contributor entry point. Deliberately excludes every title
# form that is this candidate's own primary/secondary/exploratory target
# (Product Manager, Business Analyst, Operations Analyst, ...) — this list
# exists to keep flagging titles that were NEVER the candidate's target in
# the first place, never to reintroduce the "manager" false-stop fix C
# closes for the candidate's own target roles.
FUNCTIONAL_MANAGER_SENIOR_TITLES: tuple[str, ...] = (
    "Marketing Manager",
    "Finance Manager",
    "Engineering Manager",
    "Sales Manager",
    "HR Manager",
    "Accounting Manager",
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

# --------------------------------------------------------------------------
# Matching Engine V2 — tiered, cross-domain vocabulary (job_agent.matching.
# requirements). Production-audit finding: COMMON_REQUIREMENT_KEYWORDS above
# is scoped to product/BA postings and, worse, treats every keyword it finds
# as equally strong evidence — a job mentioning only "Python" and "API" (both
# ubiquitous across nearly every technical field) scored identically to one
# whose actual, matched requirements were genuinely rare and specific. These
# two new lists split that same idea into "practically universal, therefore
# weak evidence on its own" (GENERIC) vs. "meaningfully distinguishing, real
# evidence of domain fit" (SPECIFIC) — deliberately spanning every role
# family the classifier recognizes (job_agent.matching.role_family), not
# just product/BA, since `job_agent.matching.requirements` no longer assumes
# every posting is in-domain for this candidate.
#
# Left UNCHANGED and untouched by this addition: COMMON_REQUIREMENT_KEYWORDS
# above, still used verbatim by job_agent.resume.tailor (an unrelated
# feature) exactly as before.
GENERIC_SKILL_KEYWORDS: tuple[str, ...] = (
    "Python",
    "API",
    "SQL",
    "Excel",
    "Google Sheets",
    "communication",
    "documentation",
    "cross-functional",
    "data analysis",
)

SPECIFIC_SKILL_KEYWORDS: tuple[str, ...] = (
    # Business Analysis
    "business analysis",
    "stakeholder communication",
    "stakeholder management",
    "requirements gathering",
    "process documentation",
    "business systems",
    "gap analysis",
    # Product Management (incl. UX, folded in here — no separate UX family
    # in this taxonomy, and these are real candidate-evidenced skills)
    "product roadmap",
    "roadmapping",
    "PRD",
    "backlog grooming",
    "sprint planning",
    "A/B testing",
    "user research",
    "usability research",
    "MoSCoW",
    "product strategy",
    "Figma",
    "wireframing",
    "prototyping",
    "persona development",
    "Agile",
    "Scrum",
    "Kanban",
    "JIRA",
    "Confluence",
    # Product/Business/Strategy Operations
    "KPI",
    "OKR",
    "SOP",
    "project management",
    "operations",
    "market research",
    "competitive analysis",
    "strategic planning",
    # Marketing Operations
    "campaign management",
    "marketing automation",
    "growth marketing",
    # Customer Success Operations
    "customer success",
    "churn analysis",
    "customer onboarding",
    "customer retention",
    # Data/Analytics
    "Tableau",
    "Power BI",
    "Looker",
    "data analytics",
    "dashboarding",
    "data pipeline",
    # Software Engineering
    "React",
    "Node.js",
    "TypeScript",
    "REST API",
    "unit testing",
    "software architecture",
    "backend services",
    # DevOps/SRE
    "CI/CD",
    "Kubernetes",
    "Docker",
    "infrastructure as code",
    "cloud infrastructure",
    "monitoring and alerting",
    "incident response",
    # Machine Learning/AI Engineering
    "machine learning",
    "artificial intelligence",
    "LLM",
    "generative AI",
    "model training",
    "neural network",
    "MLOps",
    # Hardware/Embedded Engineering
    "firmware",
    "embedded systems",
    "microcontroller",
    "C/C++",
    "RTOS",
    "PCB design",
    "sensor integration",
    # Aerospace/Controls/Robotics Engineering
    "control theory",
    "Kalman filter",
    "orbital mechanics",
    "MATLAB",
    "Simulink",
    "guidance navigation and control",
    "flight software",
    "finite element analysis",
    "structural analysis",
    "propulsion",
    "avionics",
    # Sales
    "quota attainment",
    "pipeline generation",
    "B2B sales",
    "account management",
    "sales cycle",
    "CRM",
    # Customer Support
    "ticketing system",
    "SLA management",
    "help desk support",
    # Finance/Accounting
    "GAAP",
    "financial modeling",
    "reconciliation",
    "financial statements",
    "accounts payable",
    "budgeting",
    # HR/Recruiting
    "talent acquisition",
    "candidate pipeline",
    "applicant tracking system",
    "employee relations",
    "HRIS",
    # Legal
    "contract review",
    "litigation",
    "compliance",
    "legal research",
    "regulatory filings",
    # Healthcare/Clinical
    "patient care",
    "clinical trial",
    "HIPAA",
    "electronic health record",
    "nursing",
    # Skilled Trades/Hospitality
    "food safety",
    "guest service",
    "kitchen operations",
    "housekeeping",
    "shift scheduling",
)

# --------------------------------------------------------------------------
# Matching Engine V3 calibration fix D: a SMALL, hand-curated, closed set
# of surface-form variants for a handful of high-value SPECIFIC_SKILL_
# KEYWORDS terms — production-audit finding: `job_agent.matching.text.
# contains_keyword`/`fuzzy_overlap` are exact-substring checks, so a
# candidate skill genuinely evidenced under one phrasing ("Roadmapping")
# was read as MISSING against a job/vocabulary phrasing that means the
# same thing but orders or inflects the words differently ("product
# roadmap"). This is deliberately NOT a stemmer or a general fuzzy-
# similarity relaxation — each group below is a fixed, explicit list of
# forms of the SAME concept, safe because every member is unambiguous on
# its own (no member is a generic word that could plausibly mean something
# else): a plural ("stakeholder communications"), a reordered verb phrase
# for the same activity ("document processes" / "gather requirements" /
# "groom backlog" for the SAME documentation/requirements-gathering/
# backlog-grooming work already in SPECIFIC_SKILL_KEYWORDS), or the noun
# root shared between a candidate's self-authored skill name and the
# vocabulary phrase for it ("roadmapping" / "roadmap" / "product
# roadmap"). Adding a new group here must meet the same bar: every member
# must be a genuine restatement of the identical activity, never a
# related-but-distinct one — this must never become a backdoor to the
# generic-keyword-overlap problem the SPECIFIC/GENERIC tiering in this
# module already exists to close.
SKILL_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"roadmapping", "roadmap", "product roadmap"}),
    frozenset({"process documentation", "document processes", "documenting processes"}),
    frozenset({"requirements gathering", "gather requirements", "gathering requirements"}),
    frozenset({"stakeholder communication", "stakeholder communications"}),
    frozenset({"backlog grooming", "groom backlog", "grooming backlog", "grooming the backlog"}),
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

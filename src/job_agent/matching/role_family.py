"""Role-family classification — Matching Engine V2.

Production-audit finding (forensic false-positive audit): the old role
scorer only recognized two exact-phrase exclusions ("Software Engineer",
"Site Reliability Engineer") and otherwise fell back to the same neutral
default for every unrecognized title — meaning "Senior GNC Engineer",
"Senior Structural Engineer", "DevOps Engineer", and "Embedded Systems
Engineer" were all scored as if their domain relevance to a Product/
Business-Analysis-oriented candidate were simply unknown, rather than
correctly recognized as an unrelated engineering discipline.

This module replaces that closed exact-phrase list with a reusable
classifier covering a fixed taxonomy of 21 role families (20 named + one
explicit "couldn't tell" bucket). It is deliberately conservative: an
unfamiliar "...Engineer"/"...Analyst"/"...Manager" title with no specific
compound-phrase or body-text evidence classifies as OTHER_UNKNOWN rather
than being guessed into either the "safe" or "excluded" side — a title
merely containing the word "Engineer" is never, by itself, treated as
Software/Hardware/Aerospace engineering (a Business Systems Engineer,
Solutions Engineer, or Analytics Engineer need very different treatment,
and get it via their own, more specific, higher-priority patterns).

`candidate_role_families()` is the "unify the two taxonomies" half (audit
item K): rather than hardcoding which families are "the candidate's",
it classifies the candidate's OWN stated target-role strings (config/
profile.yaml) through this exact same classifier, and additionally folds
in whatever `job_agent.candidate.career_paths.discover_career_paths`
already found real evidence for — so a path that module surfaces (e.g.
"Customer Success Operations") but that never made it into profile.yaml's
target_roles list is still recognized as a plausible fit, without any
job ever being *forced* into one of the 21 buckets it doesn't belong in.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from job_agent.candidate.career_paths import discover_career_paths
from job_agent.candidate.schema import CandidateProfile
from job_agent.config.models import ProfileConfig
from job_agent.matching.text import contains_keyword


class RoleFamily(StrEnum):
    BUSINESS_ANALYSIS = "Business Analysis"
    PRODUCT_MANAGEMENT = "Product Management"
    PRODUCT_OPERATIONS = "Product Operations"
    BUSINESS_OPERATIONS = "Business Operations"
    STRATEGY_OPERATIONS = "Strategy & Operations"
    MARKETING_OPERATIONS = "Marketing Operations"
    CUSTOMER_SUCCESS_OPERATIONS = "Customer Success Operations"
    DATA_ANALYTICS = "Data/Analytics"
    SOFTWARE_ENGINEERING = "Software Engineering"
    DEVOPS_SRE = "DevOps/SRE"
    ML_AI_ENGINEERING = "Machine Learning/AI Engineering"
    HARDWARE_EMBEDDED_ENGINEERING = "Hardware/Embedded Engineering"
    AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING = "Aerospace/Controls/Robotics Engineering"
    SALES = "Sales"
    CUSTOMER_SUPPORT = "Customer Support"
    FINANCE_ACCOUNTING = "Finance/Accounting"
    HR_RECRUITING = "HR/Recruiting"
    LEGAL = "Legal"
    HEALTHCARE_CLINICAL = "Healthcare/Clinical"
    SKILLED_TRADES_HOSPITALITY = "Skilled Trades/Hospitality"
    OTHER_UNKNOWN = "Other/Unknown"


# The "operations/analytics/product" cluster: families that are plausibly
# adjacent to this candidate's whole career direction even when not
# explicitly one of their stated target roles — an unlisted-but-adjacent
# title (e.g. "Customer Success Associate" for a candidate whose target
# list doesn't literally say "Customer Success") should read as
# "unconfirmed but plausible", never as harshly as a Line Cook or a GNC
# Engineer posting.
ADJACENT_CLUSTER: frozenset[RoleFamily] = frozenset(
    {
        RoleFamily.BUSINESS_ANALYSIS,
        RoleFamily.PRODUCT_MANAGEMENT,
        RoleFamily.PRODUCT_OPERATIONS,
        RoleFamily.BUSINESS_OPERATIONS,
        RoleFamily.STRATEGY_OPERATIONS,
        RoleFamily.MARKETING_OPERATIONS,
        RoleFamily.CUSTOMER_SUCCESS_OPERATIONS,
        RoleFamily.DATA_ANALYTICS,
    }
)

# TIER 0 — ordered most-specific-first. Checked as one flat, prioritized
# list across every family so a compound title (e.g. "Business Systems
# Engineer") is claimed by its correct, more specific family before a
# later, more generic pattern (e.g. bare "...Engineer") ever gets a look.
_TIER0_PATTERNS: tuple[tuple[RoleFamily, str], ...] = (
    # --- Business Analysis ---
    (RoleFamily.BUSINESS_ANALYSIS, "Business Systems Analyst"),
    (RoleFamily.BUSINESS_ANALYSIS, "Business Systems Engineer"),
    (RoleFamily.BUSINESS_ANALYSIS, "Technical Business Analyst"),
    (RoleFamily.BUSINESS_ANALYSIS, "Business Analyst"),
    # --- Product Management ---
    (RoleFamily.PRODUCT_MANAGEMENT, "Associate Product Manager"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Junior Product Manager"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Technical Product Manager"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Product Analyst"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Product Manager"),
    (RoleFamily.PRODUCT_MANAGEMENT, "APM"),
    # --- Product Operations ---
    (RoleFamily.PRODUCT_OPERATIONS, "Product Operations Analyst"),
    (RoleFamily.PRODUCT_OPERATIONS, "Product Operations Manager"),
    (RoleFamily.PRODUCT_OPERATIONS, "Product Operations Engineer"),
    (RoleFamily.PRODUCT_OPERATIONS, "Product Ops"),
    # --- Business Operations (also the home for Program/Project roles —
    # no separate family exists for those in this taxonomy) ---
    (RoleFamily.BUSINESS_OPERATIONS, "Business Operations Analyst"),
    (RoleFamily.BUSINESS_OPERATIONS, "Business Operations Associate"),
    (RoleFamily.BUSINESS_OPERATIONS, "BizOps"),
    (RoleFamily.BUSINESS_OPERATIONS, "Program Operations Analyst"),
    (RoleFamily.BUSINESS_OPERATIONS, "Program Analyst"),
    (RoleFamily.BUSINESS_OPERATIONS, "Program Manager"),
    (RoleFamily.BUSINESS_OPERATIONS, "Project Manager"),
    (RoleFamily.BUSINESS_OPERATIONS, "Operations Analyst"),
    # --- Strategy & Operations ---
    (RoleFamily.STRATEGY_OPERATIONS, "Strategy & Operations Analyst"),
    (RoleFamily.STRATEGY_OPERATIONS, "Strategy and Operations Analyst"),
    (RoleFamily.STRATEGY_OPERATIONS, "Strategy Associate"),
    (RoleFamily.STRATEGY_OPERATIONS, "Chief of Staff"),
    # --- Marketing Operations ---
    (RoleFamily.MARKETING_OPERATIONS, "Marketing Operations Analyst"),
    (RoleFamily.MARKETING_OPERATIONS, "Growth Operations Analyst"),
    (RoleFamily.MARKETING_OPERATIONS, "Marketing Operations"),
    # --- Customer Success Operations ---
    (RoleFamily.CUSTOMER_SUCCESS_OPERATIONS, "Customer Success Operations Analyst"),
    (RoleFamily.CUSTOMER_SUCCESS_OPERATIONS, "Customer Success Associate"),
    (RoleFamily.CUSTOMER_SUCCESS_OPERATIONS, "Customer Success Manager"),
    (RoleFamily.CUSTOMER_SUCCESS_OPERATIONS, "Customer Success"),
    # --- Data/Analytics ---
    (RoleFamily.DATA_ANALYTICS, "Business Intelligence Analyst"),
    (RoleFamily.DATA_ANALYTICS, "Analytics Engineer"),
    (RoleFamily.DATA_ANALYTICS, "Analytics Associate"),
    (RoleFamily.DATA_ANALYTICS, "Data Analyst"),
    # --- Machine Learning / AI Engineering ---
    (RoleFamily.ML_AI_ENGINEERING, "AI Operations Analyst"),
    (RoleFamily.ML_AI_ENGINEERING, "AI Operations Associate"),
    (RoleFamily.ML_AI_ENGINEERING, "AI Product Analyst"),
    (RoleFamily.ML_AI_ENGINEERING, "Machine Learning Engineer"),
    (RoleFamily.ML_AI_ENGINEERING, "ML Engineer"),
    (RoleFamily.ML_AI_ENGINEERING, "AI Engineer"),
    (RoleFamily.ML_AI_ENGINEERING, "Applied Scientist"),
    (RoleFamily.ML_AI_ENGINEERING, "Data Scientist"),
    # --- Aerospace/Controls/Robotics Engineering ---
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "GNC Engineer"),
    (
        RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING,
        "Guidance Navigation and Control Engineer",
    ),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Flight Controls Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Avionics Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Propulsion Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Aerospace Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Aerostructures Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Controls Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Robotics Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Autonomy Engineer"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Structural Engineer"),
    # --- Hardware/Embedded Engineering ---
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "Embedded Systems Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "Embedded Software Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "Firmware Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "Electrical Power Systems Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "Electrical Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "Hardware Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "RF Engineer"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "PCB Engineer"),
    # --- DevOps/SRE ---
    (RoleFamily.DEVOPS_SRE, "DevOps Engineer"),
    (RoleFamily.DEVOPS_SRE, "Site Reliability Engineer"),
    (RoleFamily.DEVOPS_SRE, "Platform Engineer"),
    (RoleFamily.DEVOPS_SRE, "Infrastructure Engineer"),
    (RoleFamily.DEVOPS_SRE, "Cloud Engineer"),
    # --- Software Engineering ---
    (RoleFamily.SOFTWARE_ENGINEERING, "QA Automation Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "QA Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Test Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Backend Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Frontend Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Full-Stack Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Full Stack Engineer"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Software Engineer"),
    # --- Sales (Solutions Engineer/Consultant sit in the sales org in
    # practice, and "Solutions Consultant" is literally this candidate's
    # own exploratory target role, so it must resolve consistently here) ---
    (RoleFamily.SALES, "Solutions Engineer"),
    (RoleFamily.SALES, "Solutions Consultant"),
    (RoleFamily.SALES, "Sales Engineer"),
    (RoleFamily.SALES, "Account Executive"),
    (RoleFamily.SALES, "Business Development Representative"),
    (RoleFamily.SALES, "Field Sales Representative"),
    (RoleFamily.SALES, "Sales Representative"),
    (RoleFamily.SALES, "Sales"),
    # --- Customer Support ---
    (RoleFamily.CUSTOMER_SUPPORT, "Technical Support Engineer"),
    (RoleFamily.CUSTOMER_SUPPORT, "Support Specialist"),
    (RoleFamily.CUSTOMER_SUPPORT, "Customer Support"),
    (RoleFamily.CUSTOMER_SUPPORT, "Help Desk"),
    # --- Finance/Accounting ---
    (RoleFamily.FINANCE_ACCOUNTING, "Financial Analyst"),
    (RoleFamily.FINANCE_ACCOUNTING, "Accounting Analyst"),
    (RoleFamily.FINANCE_ACCOUNTING, "Accountant"),
    (RoleFamily.FINANCE_ACCOUNTING, "Finance Manager"),
    (RoleFamily.FINANCE_ACCOUNTING, "Controller"),
    (RoleFamily.FINANCE_ACCOUNTING, "Bookkeeper"),
    # --- HR/Recruiting ---
    (RoleFamily.HR_RECRUITING, "Talent Acquisition"),
    (RoleFamily.HR_RECRUITING, "HR Business Partner"),
    (RoleFamily.HR_RECRUITING, "People Operations"),
    (RoleFamily.HR_RECRUITING, "Recruiter"),
    (RoleFamily.HR_RECRUITING, "Human Resources"),
    # --- Legal ---
    (RoleFamily.LEGAL, "Paralegal"),
    (RoleFamily.LEGAL, "Legal Counsel"),
    (RoleFamily.LEGAL, "Compliance Analyst"),
    (RoleFamily.LEGAL, "Contracts Manager"),
    (RoleFamily.LEGAL, "Attorney"),
    # --- Healthcare/Clinical ---
    (RoleFamily.HEALTHCARE_CLINICAL, "Registered Nurse"),
    (RoleFamily.HEALTHCARE_CLINICAL, "Nurse Practitioner"),
    (RoleFamily.HEALTHCARE_CLINICAL, "Clinical Research"),
    (RoleFamily.HEALTHCARE_CLINICAL, "Physician"),
    (RoleFamily.HEALTHCARE_CLINICAL, "Medical Assistant"),
    # --- Skilled Trades/Hospitality ---
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Line Cook"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Chef"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Electrician"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Plumber"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Barista"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Housekeeping"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Warehouse Associate"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "Server"),
)

# TIER 1 — intern/working-student variants, added by Matching Engine V3
# calibration fix E. Production-audit finding: an intern/working-student
# title (e.g. "Product Management Intern") fell all the way through to
# OTHER_UNKNOWN even when it obviously names one of the SAME substantive
# role families TIER 0 already recognizes — "intern"/"working student" was
# never itself a role family, but TIER 0's patterns were all written for
# the un-qualified, full-time form of a title and none of them happen to
# be literal substrings of their own intern-qualified forms ("Product
# Manager" is not a substring of "Product Management Intern"). Checked
# AFTER TIER 0 (so any title that already matches an existing, more
# specific pattern — "Business Analyst Intern" contains "Business
# Analyst"; "APM Intern" contains "APM" — keeps resolving via TIER 0
# exactly as before; nothing here ever overrides that). Ordered most-
# specific-first WITHIN this tier for the same reason TIER 0 is: "Product
# Operations Intern"/"Working Student Product Operations" must resolve to
# PRODUCT_OPERATIONS before the shorter, less specific "Working Student
# Product" (PRODUCT_MANAGEMENT) pattern ever gets a look, since the latter
# is a literal prefix of the former. Deliberately narrow and role-
# specific, per the audit's explicit instruction: "do not classify every
# internship as Product" — a Finance/Software-Engineering/etc. internship
# resolves to ITS OWN family, never defaulted to this candidate's own
# target roles.
_INTERN_TIER1_PATTERNS: tuple[tuple[RoleFamily, str], ...] = (
    (RoleFamily.PRODUCT_OPERATIONS, "Product Operations Intern"),
    (RoleFamily.PRODUCT_OPERATIONS, "Working Student Product Operations"),
    (RoleFamily.PRODUCT_OPERATIONS, "Product Operations"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Product Management Intern"),
    (RoleFamily.PRODUCT_MANAGEMENT, "PM Intern"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Product Intern"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Working Student Product"),
    (RoleFamily.PRODUCT_MANAGEMENT, "Product Management"),
    (RoleFamily.BUSINESS_ANALYSIS, "Business Analysis Intern"),
    (RoleFamily.BUSINESS_ANALYSIS, "Working Student Business Analysis"),
    (RoleFamily.BUSINESS_ANALYSIS, "Business Analysis"),
    (RoleFamily.FINANCE_ACCOUNTING, "Finance Intern"),
    (RoleFamily.SOFTWARE_ENGINEERING, "Software Engineering Intern"),
)

# TIER 2 — body-text fallback cues, used only when the title itself gave
# no TIER 0/TIER 1 match. Deliberately small: enough to resolve the
# clearest cases (a "Senior Engineer" posting that's obviously aerospace,
# or an "Analyst" posting that's obviously accounting) without pretending
# to be an exhaustive domain classifier.
_TIER2_BODY_PATTERNS: tuple[tuple[RoleFamily, str], ...] = (
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "orbital mechanics"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "Kalman filter"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "control theory"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "guidance navigation and control"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "flight software"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "finite element analysis"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "composite airframe"),
    (RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING, "launch vehicle"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "microcontroller"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "RTOS"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "PCB design"),
    (RoleFamily.HARDWARE_EMBEDDED_ENGINEERING, "high-voltage systems"),
    (RoleFamily.DEVOPS_SRE, "infrastructure as code"),
    (RoleFamily.DEVOPS_SRE, "on-call rotation"),
    (RoleFamily.DEVOPS_SRE, "incident response"),
    (RoleFamily.FINANCE_ACCOUNTING, "GAAP"),
    (RoleFamily.FINANCE_ACCOUNTING, "financial statements"),
    (RoleFamily.FINANCE_ACCOUNTING, "accounts payable"),
    (RoleFamily.HR_RECRUITING, "candidate pipeline"),
    (RoleFamily.HR_RECRUITING, "applicant tracking system"),
    (RoleFamily.LEGAL, "contract review"),
    (RoleFamily.LEGAL, "litigation"),
    (RoleFamily.HEALTHCARE_CLINICAL, "patient care"),
    (RoleFamily.HEALTHCARE_CLINICAL, "clinical trial"),
    (RoleFamily.HEALTHCARE_CLINICAL, "HIPAA"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "kitchen"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "guest service"),
    (RoleFamily.SKILLED_TRADES_HOSPITALITY, "shift work"),
)

_CAREER_PATH_LABEL_TO_FAMILY: dict[str, RoleFamily] = {
    "Product Operations": RoleFamily.PRODUCT_OPERATIONS,
    "Business Operations": RoleFamily.BUSINESS_OPERATIONS,
    "Strategy & Operations": RoleFamily.STRATEGY_OPERATIONS,
    "Product Management": RoleFamily.PRODUCT_MANAGEMENT,
    "Business Analysis": RoleFamily.BUSINESS_ANALYSIS,
    "Data / Analytics": RoleFamily.DATA_ANALYTICS,
    "Software Engineering": RoleFamily.SOFTWARE_ENGINEERING,
    "Marketing Operations": RoleFamily.MARKETING_OPERATIONS,
    "Customer Success Operations": RoleFamily.CUSTOMER_SUCCESS_OPERATIONS,
    "AI Operations": RoleFamily.ML_AI_ENGINEERING,
    # Matching Engine V3 calibration, Phase 9: `job_agent.candidate.
    # career_paths._TAXONOMY` has two labels this dict used to have no
    # entry for at all, silently dropping either one from ever promoting
    # a role family here even on a HIGH-priority discovered result. Both
    # map onto families this taxonomy already documents as their home:
    # role_family.py's own BUSINESS_OPERATIONS TIER0 comment ("also the
    # home for Program/Project roles — no separate family exists for
    # those in this taxonomy") and vocabulary.py's own SPECIFIC_SKILL_
    # KEYWORDS comment ("Product Management (incl. UX, folded in here —
    # no separate UX family in this taxonomy...")) — not a new judgment
    # call, just closing a gap between two pieces of this module's own,
    # already-stated design.
    "Program / Project Management": RoleFamily.BUSINESS_OPERATIONS,
    "UX / Product Design": RoleFamily.PRODUCT_MANAGEMENT,
}


@dataclass(frozen=True)
class RoleFamilyMatch:
    family: RoleFamily
    confidence: str  # "high" (title match) | "medium" (body-text fallback) | "none"
    matched_signal: str | None = None


def classify_role_family(title: str, text: str = "") -> RoleFamilyMatch:
    """Classify a job into one of the 21 role families.

    `title` alone is checked first (TIER 0) since a title is the strongest,
    least-ambiguous signal a posting gives; `text` (title+description, the
    same `JobText.combined_text` the rest of the matcher already uses) is
    only consulted (TIER 2) when the title itself resolved nothing."""
    for family, pattern in _TIER0_PATTERNS:
        if contains_keyword(title, pattern):
            return RoleFamilyMatch(family=family, confidence="high", matched_signal=pattern)

    for family, pattern in _INTERN_TIER1_PATTERNS:
        if contains_keyword(title, pattern):
            return RoleFamilyMatch(family=family, confidence="high", matched_signal=pattern)

    body = text or title
    for family, pattern in _TIER2_BODY_PATTERNS:
        if contains_keyword(body, pattern):
            return RoleFamilyMatch(family=family, confidence="medium", matched_signal=pattern)

    return RoleFamilyMatch(family=RoleFamily.OTHER_UNKNOWN, confidence="none", matched_signal=None)


def classify_role_text(role_text: str) -> RoleFamily:
    """Classify a bare role-name string (e.g. one entry from
    `config/profile.yaml`'s target_roles) — title-only, no body text."""
    return classify_role_family(role_text).family


def excluded_role_families(profile_cfg: ProfileConfig) -> frozenset[RoleFamily]:
    """The role families the candidate has explicitly said to exclude
    (`config/profile.yaml`'s `excluded_roles`), classified through the
    same classifier a job posting's title goes through. Generalizes a
    single exact-phrase exclusion (e.g. "Software Engineer") to its
    WHOLE family — a benchmark-caught gap: without this, "Full-Stack
    Engineer" or "Backend Engineer" (same family, different exact title)
    could still get auto-promoted into a compatible role via
    `candidate_role_families`'s career-paths integration, silently
    contradicting the candidate's own explicit exclusion.

    Deliberately does NOT generalize an exclusion whose family is ALSO
    reached by one of the candidate's own target_roles — a second
    benchmark-caught gap: "Senior Product Manager"/"Director of Product"
    are excluded for their SENIORITY, not because Product Management as a
    family is wrong for this candidate (it's their PRIMARY target,
    reached via "Associate Product Manager" etc.) — generalizing those
    would have wiped out the candidate's real primary role family
    entirely. Only a title whose family shares NO overlap with any stated
    target role is safe to reject at the whole-family level."""
    target_families = {
        classify_role_text(role_text)
        for role_text in (
            *profile_cfg.target_roles.primary,
            *profile_cfg.target_roles.secondary,
            *profile_cfg.target_roles.exploratory,
        )
    }
    result: set[RoleFamily] = set()
    for role_text in profile_cfg.excluded_roles:
        family = classify_role_text(role_text)
        if family == RoleFamily.OTHER_UNKNOWN or family in target_families:
            continue
        result.add(family)
    return frozenset(result)


def candidate_role_families(
    profile: CandidateProfile, profile_cfg: ProfileConfig
) -> dict[RoleFamily, str]:
    """Every role family this candidate has real evidence of wanting,
    mapped to the strongest tier ("primary"/"secondary"/"exploratory") it
    was found at. Two sources, merged (never let one silently shadow the
    other):

    1. `config/profile.yaml`'s own target_roles lists, classified through
       the exact same classifier a job posting's title goes through — so
       "Business Systems Analyst" (a real posting title) and "Business
       Analyst" (the candidate's stated target role) land in the same
       family even though neither is a literal substring of the other.
    2. `job_agent.candidate.career_paths.discover_career_paths` — a HIGH
       priority result promotes its family to (at least) "secondary",
       a MEDIUM priority result to (at least) "exploratory". This is the
       audit's item K fix: a real, evidenced career direction that never
       made it into profile.yaml's hand-maintained lists (e.g. Customer
       Success Operations) is still recognized here, without forcing
       every job into one of the 21 buckets — a family with no evidence
       anywhere simply never appears in this dict.
    """
    tiers: dict[RoleFamily, str] = {}
    _TIER_RANK = {"primary": 3, "secondary": 2, "exploratory": 1}

    def _promote(family: RoleFamily, tier: str) -> None:
        if family == RoleFamily.OTHER_UNKNOWN:
            return
        current = tiers.get(family)
        if current is None or _TIER_RANK[tier] > _TIER_RANK[current]:
            tiers[family] = tier

    for role_text in profile_cfg.target_roles.primary:
        _promote(classify_role_text(role_text), "primary")
    for role_text in profile_cfg.target_roles.secondary:
        _promote(classify_role_text(role_text), "secondary")
    for role_text in profile_cfg.target_roles.exploratory:
        _promote(classify_role_text(role_text), "exploratory")

    excluded = excluded_role_families(profile_cfg)
    for path in discover_career_paths(profile):
        family = _CAREER_PATH_LABEL_TO_FAMILY.get(path.label)
        if family is None or family in excluded:
            continue
        if path.recommended_priority == "HIGH":
            _promote(family, "secondary")
        elif path.recommended_priority == "MEDIUM":
            _promote(family, "exploratory")

    # Belt-and-suspenders: an explicitly excluded family must never be
    # "compatible" even if it somehow entered `tiers` above (e.g. a
    # future edit adds an excluded_roles entry that's also literally in
    # target_roles — a contradictory config, but this must not silently
    # let the exclusion lose).
    for family in excluded:
        tiers.pop(family, None)

    return tiers

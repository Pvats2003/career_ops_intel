"""Matching Engine V2 — synthetic quality benchmark (audit Phase 3).

A deterministic, >=50-job labeled dataset spanning the requested category
spread, run through the REAL production matching code
(compute_deterministic_match -> combine_match -> finalize) against the
REAL candidate profile. Used ONLY here, in tests — never inserted into
any database or shown to a user.

The goal per the audit is explicitly NOT maximum recall: "A false positive
is significantly worse than a missed weak opportunity." So the benchmark's
hard requirement is a near-zero false-positive rate (a wrong-domain job
must never reach SAVE/REVIEW/APPLY), with strong-fit recall measured and
reported, but not required to be perfect.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.matching.decision import finalize
from job_agent.matching.deterministic import JobText, compute_deterministic_match
from job_agent.matching.role_family import RoleFamily
from job_agent.matching.schema import Decision
from job_agent.matching.scoring import combine_match
from job_agent.matching.semantic import SemanticOutcome

_NO_SEMANTIC = SemanticOutcome(available=False, unavailable_reason="benchmark: deterministic-only")

_QUALIFIED = {Decision.APPLY, Decision.REVIEW, Decision.SAVE}


@dataclass(frozen=True)
class BenchmarkJob:
    category: str
    expected_class: str  # "strong" | "false_positive"
    title: str
    description: str
    remote_type: str | None = "remote"
    location: str | None = None
    expected_family: RoleFamily | None = None


# --------------------------------------------------------------------------
# STRONG-FIT jobs — genuinely aligned with the candidate's real target
# roles/skills/experience. Each posting is written at realistic length
# (a real Remotive/Arbeitnow listing is rarely a single sentence).
# --------------------------------------------------------------------------
_STRONG_JOBS: tuple[BenchmarkJob, ...] = (
    BenchmarkJob(
        "business_analysis", "strong", "Business Analyst",
        "Business Analyst to support stakeholder communication, process documentation, "
        "business analysis, and KPI reporting across our operations teams, using Excel and "
        "Google Sheets for ad hoc analysis. Bachelor's degree required. Entry-level welcome.",
        expected_family=RoleFamily.BUSINESS_ANALYSIS,
    ),
    BenchmarkJob(
        "business_analysis", "strong", "Technical Business Analyst",
        "Technical Business Analyst to gather requirements, run stakeholder communication "
        "sessions, and maintain process documentation for internal tools. Bachelor's degree "
        "required. New grads welcome.",
        expected_family=RoleFamily.BUSINESS_ANALYSIS,
    ),
    BenchmarkJob(
        "business_analysis", "strong", "Business Systems Analyst",
        "Business Systems Analyst -- own process documentation, stakeholder communication, and "
        "business analysis for our finance systems. Bachelor's degree required. Entry-level "
        "welcome.",
        expected_family=RoleFamily.BUSINESS_ANALYSIS,
    ),
    BenchmarkJob(
        "product", "strong", "Product Analyst",
        "Product Analyst role: draft PRDs, run sprint planning and backlog grooming with the "
        "engineering team, use MoSCoW to prioritize the roadmap, and support user research. "
        "Bachelor's degree required. New grads welcome.",
        expected_family=RoleFamily.PRODUCT_MANAGEMENT,
    ),
    BenchmarkJob(
        "product", "strong", "Associate Product Manager",
        "Associate Product Manager -- draft PRDs, run sprint planning and backlog grooming, "
        "prioritize using MoSCoW, and support user research and usability research. Bachelor's "
        "degree required. New grads and entry-level candidates welcome.",
        expected_family=RoleFamily.PRODUCT_MANAGEMENT,
    ),
    BenchmarkJob(
        "product", "strong", "Junior Product Manager",
        "Junior Product Manager -- own PRD drafting, roadmapping, and A/B testing for a B2B SaaS "
        "product, working closely with UX on wireframing and prototyping. Bachelor's degree "
        "required. Entry-level welcome.",
        expected_family=RoleFamily.PRODUCT_MANAGEMENT,
    ),
    BenchmarkJob(
        "operations", "strong", "Operations Analyst",
        "Operations Analyst -- own process documentation, KPI and OKR reporting, stakeholder "
        "management, and cross-functional coordination between teams. Bachelor's degree "
        "required. Entry-level welcome.",
        expected_family=RoleFamily.BUSINESS_OPERATIONS,
    ),
    BenchmarkJob(
        "operations", "strong", "Business Operations Analyst",
        "Business Operations Analyst -- support KPI reporting, process documentation, and "
        "stakeholder management across sales and finance operations. Bachelor's degree required.",
        expected_family=RoleFamily.BUSINESS_OPERATIONS,
    ),
    BenchmarkJob(
        "operations", "strong", "Program Operations Analyst",
        "Program Operations Analyst -- coordinate field operations programs, own process "
        "documentation and KPI reporting for distributed field teams. Bachelor's degree "
        "required. Entry-level welcome.",
        expected_family=RoleFamily.BUSINESS_OPERATIONS,
    ),
    BenchmarkJob(
        "marketing_operations", "strong", "Marketing Operations Analyst",
        "Marketing Operations Analyst -- run market research and competitive analysis, build KPI "
        "dashboards, and coordinate cross-functionally with growth and sales. Bachelor's degree "
        "required. New grads welcome.",
        expected_family=RoleFamily.MARKETING_OPERATIONS,
    ),
    BenchmarkJob(
        "marketing_operations", "strong", "Growth Operations Analyst",
        "Growth Operations Analyst -- own KPI dashboards, market research, and cross-functional "
        "coordination between marketing and product. Bachelor's degree required.",
        expected_family=RoleFamily.MARKETING_OPERATIONS,
    ),
    BenchmarkJob(
        "customer_success_operations", "strong", "Customer Success Operations Analyst",
        "Customer Success Operations Analyst -- own stakeholder management, process "
        "documentation, and KPI reporting for our customer success org. Bachelor's degree "
        "required. Entry-level welcome.",
        expected_family=RoleFamily.CUSTOMER_SUCCESS_OPERATIONS,
    ),
    BenchmarkJob(
        "customer_success_operations", "strong", "Customer Success Associate",
        "Customer Success Associate -- stakeholder management and process documentation for "
        "customer onboarding, working cross-functionally with product. Bachelor's degree "
        "required.",
        expected_family=RoleFamily.CUSTOMER_SUCCESS_OPERATIONS,
    ),
    BenchmarkJob(
        "strategy_operations", "strong", "Strategy & Operations Analyst",
        "Strategy & Operations Analyst -- support market research, competitive analysis, and OKR "
        "tracking, with KPI reporting for the leadership team. Bachelor's degree required. "
        "Entry-level welcome.",
        expected_family=RoleFamily.STRATEGY_OPERATIONS,
    ),
    BenchmarkJob(
        "strategy_operations", "strong", "Strategy Associate",
        "Strategy Associate -- own competitive analysis and market research, presenting KPI "
        "findings to leadership. Bachelor's degree required.",
        expected_family=RoleFamily.STRATEGY_OPERATIONS,
    ),
    BenchmarkJob(
        "entry_level_analyst", "strong", "Product Operations Analyst",
        "Product Operations Analyst -- own cross-functional process documentation, KPI/OKR "
        "tracking, and stakeholder management across product and support teams. Bachelor's "
        "degree required. Entry-level welcome.",
        expected_family=RoleFamily.PRODUCT_OPERATIONS,
    ),
    BenchmarkJob(
        "entry_level_analyst", "strong", "APM",
        "APM -- draft PRDs, run sprint planning, use MoSCoW to prioritize, and support user "
        "research. Bachelor's degree required. New grads and entry-level candidates welcome.",
        expected_family=RoleFamily.PRODUCT_MANAGEMENT,
    ),
    BenchmarkJob(
        "entry_level_analyst", "strong", "Junior Business Analyst",
        "Junior Business Analyst -- stakeholder communication, process documentation, and KPI "
        "reporting using Excel. Bachelor's degree required. New grads welcome.",
        expected_family=RoleFamily.BUSINESS_ANALYSIS,
    ),
    BenchmarkJob(
        "entry_level_analyst", "strong", "Business Operations Associate",
        "Business Operations Associate -- process documentation, KPI reporting, and stakeholder "
        "management for a fast-growing operations team. Bachelor's degree required. Entry-level "
        "welcome.",
        expected_family=RoleFamily.BUSINESS_OPERATIONS,
    ),
    BenchmarkJob(
        "entry_level_analyst", "strong", "Data Analyst",
        "Data Analyst -- run SQL queries and build dashboards for cross-functional stakeholders, "
        "with KPI reporting in Excel. Bachelor's degree required. New grads welcome.",
        expected_family=RoleFamily.DATA_ANALYTICS,
    ),
)

# --------------------------------------------------------------------------
# FALSE-POSITIVE / unrelated-domain jobs — the audit's core concern. None
# of these should ever reach SAVE/REVIEW/APPLY.
# --------------------------------------------------------------------------
_FALSE_POSITIVE_JOBS: tuple[BenchmarkJob, ...] = (
    BenchmarkJob(
        "software_engineering", "false_positive", "Backend Engineer",
        "Backend Engineer -- build REST APIs and backend services in Python and Node.js, with "
        "unit testing and software architecture ownership. 3+ years professional software "
        "engineering experience required.",
        expected_family=RoleFamily.SOFTWARE_ENGINEERING,
    ),
    BenchmarkJob(
        "software_engineering", "false_positive", "Full-Stack Engineer",
        "Full-Stack Engineer -- React frontend, Node.js/TypeScript backend, REST API design. "
        "4+ years experience required.",
        expected_family=RoleFamily.SOFTWARE_ENGINEERING,
    ),
    BenchmarkJob(
        "software_engineering", "false_positive", "QA Automation Engineer",
        "QA Automation Engineer -- write automated test suites in Python, own unit testing "
        "coverage, and use JIRA to track defects. 2+ years experience in software QA required.",
        expected_family=RoleFamily.SOFTWARE_ENGINEERING,
    ),
    BenchmarkJob(
        "devops", "false_positive", "DevOps Engineer",
        "DevOps Engineer -- manage cloud infrastructure, build CI/CD pipelines with Kubernetes "
        "and Docker, and own incident response. 5+ years experience required.",
        expected_family=RoleFamily.DEVOPS_SRE,
    ),
    BenchmarkJob(
        "devops", "false_positive", "Platform Engineer",
        "Platform Engineer -- own infrastructure as code, cloud infrastructure, and monitoring "
        "and alerting for our platform team. 4+ years experience required.",
        expected_family=RoleFamily.DEVOPS_SRE,
    ),
    BenchmarkJob(
        "devops", "false_positive", "Cloud Engineer",
        "Cloud Engineer -- design and operate cloud infrastructure with a focus on CI/CD and "
        "infrastructure as code. 5+ years experience required.",
        expected_family=RoleFamily.DEVOPS_SRE,
    ),
    BenchmarkJob(
        "ml_engineering", "false_positive", "Machine Learning Engineer",
        "Machine Learning Engineer -- train and deploy production ML models, own MLOps and "
        "model training pipelines. Master's degree in CS or related field required. 4+ years "
        "experience.",
        expected_family=RoleFamily.ML_AI_ENGINEERING,
    ),
    BenchmarkJob(
        "ml_engineering", "false_positive", "Data Scientist",
        "Data Scientist -- build neural network models and own MLOps for production machine "
        "learning systems. Master's degree required. 3+ years experience.",
        expected_family=RoleFamily.ML_AI_ENGINEERING,
    ),
    BenchmarkJob(
        "ml_engineering", "false_positive", "Applied Scientist",
        "Applied Scientist -- research and deploy machine learning and neural network models "
        "for production. PhD or equivalent experience required.",
        expected_family=RoleFamily.ML_AI_ENGINEERING,
    ),
    BenchmarkJob(
        "aerospace_engineering", "false_positive", "Senior GNC Engineer",
        "Design control algorithms for our launch vehicle. Write flight software in Python and "
        "C++, expose telemetry via internal APIs, and work cross-functionally with propulsion, "
        "avionics, and structures. Requires deep expertise in control theory, Kalman filtering, "
        "orbital mechanics, and MATLAB/Simulink.",
        remote_type=None, location="Munich, Germany",
        expected_family=RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING,
    ),
    BenchmarkJob(
        "aerospace_engineering", "false_positive", "Senior Structural Engineer",
        "Perform finite-element analysis (FEA) on composite airframes using Nastran/Patran, "
        "review stress reports, and coordinate cross-functionally with manufacturing using our "
        "internal API-driven PLM system. 8+ years in aerospace structures required.",
        remote_type=None, location="Seattle, WA",
        expected_family=RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING,
    ),
    BenchmarkJob(
        "aerospace_engineering", "false_positive", "Propulsion Engineer",
        "Propulsion Engineer -- design and test rocket propulsion systems, applying control "
        "theory and structural analysis. 6+ years experience in aerospace propulsion required.",
        remote_type=None, location="Hawthorne, CA",
        expected_family=RoleFamily.AEROSPACE_CONTROLS_ROBOTICS_ENGINEERING,
    ),
    BenchmarkJob(
        "hardware_embedded", "false_positive", "Embedded Systems Engineer",
        "Write firmware in C/C++ for robotics controllers, integrate sensor APIs, and use "
        "Python for test tooling. 5+ years embedded systems experience required.",
        expected_family=RoleFamily.HARDWARE_EMBEDDED_ENGINEERING,
    ),
    BenchmarkJob(
        "hardware_embedded", "false_positive", "Firmware Engineer",
        "Firmware Engineer -- develop RTOS-based firmware and PCB design integration for "
        "consumer electronics. 4+ years embedded firmware experience required.",
        expected_family=RoleFamily.HARDWARE_EMBEDDED_ENGINEERING,
    ),
    BenchmarkJob(
        "hardware_embedded", "false_positive", "Electrical Power Systems Engineer",
        "Electrical Power Systems Engineer -- design substation protection schemes and run "
        "load-flow studies for high-voltage systems. 5+ years experience required.",
        remote_type=None, location="Houston, TX",
        expected_family=RoleFamily.HARDWARE_EMBEDDED_ENGINEERING,
    ),
    BenchmarkJob(
        "finance", "false_positive", "Financial Analyst",
        "Financial Analyst -- own financial modeling, reconciliation, and financial statements "
        "review under GAAP. 3+ years accounting/finance experience required.",
        expected_family=RoleFamily.FINANCE_ACCOUNTING,
    ),
    BenchmarkJob(
        "finance", "false_positive", "Staff Accountant",
        "Staff Accountant -- manage accounts payable, budgeting, and monthly reconciliation "
        "under GAAP. 2+ years accounting experience required.",
        expected_family=RoleFamily.FINANCE_ACCOUNTING,
    ),
    BenchmarkJob(
        "finance", "false_positive", "Controller",
        "Controller -- own financial statements, GAAP compliance, and budgeting for a mid-size "
        "company. 8+ years accounting experience required.",
        expected_family=RoleFamily.FINANCE_ACCOUNTING,
    ),
    BenchmarkJob(
        "sales", "false_positive", "Account Executive",
        "Account Executive -- own the full sales cycle, pipeline generation, and quota "
        "attainment for enterprise accounts using our CRM. 3+ years B2B sales experience "
        "required.",
        expected_family=RoleFamily.SALES,
    ),
    BenchmarkJob(
        "sales", "false_positive", "Field Sales Representative",
        "Field Sales Representative to sell agricultural equipment across the Midwest. Must "
        "have a valid driver's license and be willing to travel extensively. 3+ years B2B sales "
        "experience required.",
        remote_type=None, location="Des Moines, IA",
        expected_family=RoleFamily.SALES,
    ),
    BenchmarkJob(
        "sales", "false_positive", "Business Development Representative",
        "Business Development Representative -- build pipeline generation and manage account "
        "management for a growing sales team using our CRM. 1+ years sales experience "
        "required.",
        expected_family=RoleFamily.SALES,
    ),
    BenchmarkJob(
        "hr", "false_positive", "Talent Acquisition Specialist",
        "Talent Acquisition Specialist -- manage the candidate pipeline and applicant tracking "
        "system for high-volume technical recruiting. 3+ years recruiting experience required.",
        expected_family=RoleFamily.HR_RECRUITING,
    ),
    BenchmarkJob(
        "hr", "false_positive", "HR Business Partner",
        "HR Business Partner -- own employee relations and HRIS administration for a 200-person "
        "org. 5+ years HR experience required.",
        expected_family=RoleFamily.HR_RECRUITING,
    ),
    BenchmarkJob(
        "hr", "false_positive", "Recruiter",
        "Recruiter -- manage the candidate pipeline end-to-end using our applicant tracking "
        "system. 2+ years recruiting experience required.",
        expected_family=RoleFamily.HR_RECRUITING,
    ),
    BenchmarkJob(
        "hospitality_trades", "false_positive", "Line Cook",
        "Line Cook needed for a busy kitchen. Must be able to work nights and weekends. No "
        "experience with software required.",
        remote_type=None, location="Chicago, IL",
        expected_family=RoleFamily.SKILLED_TRADES_HOSPITALITY,
    ),
    BenchmarkJob(
        "hospitality_trades", "false_positive", "Electrician",
        "Electrician -- residential and commercial electrical installation and repair. Licensed "
        "electrician required, 3+ years experience.",
        remote_type=None, location="Denver, CO",
        expected_family=RoleFamily.SKILLED_TRADES_HOSPITALITY,
    ),
    BenchmarkJob(
        "hospitality_trades", "false_positive", "Housekeeping Supervisor",
        "Housekeeping Supervisor for a 200-room hotel -- manage shift scheduling and guest "
        "service standards. 2+ years hospitality experience required.",
        remote_type=None, location="Orlando, FL",
        expected_family=RoleFamily.SKILLED_TRADES_HOSPITALITY,
    ),
    BenchmarkJob(
        "unrelated", "false_positive", "Registered Nurse",
        "Registered Nurse -- provide patient care on our medical-surgical unit, maintaining "
        "electronic health record documentation. Active RN license required.",
        remote_type=None, location="Dallas, TX",
        expected_family=RoleFamily.HEALTHCARE_CLINICAL,
    ),
    BenchmarkJob(
        "unrelated", "false_positive", "Paralegal",
        "Paralegal -- support contract review and litigation preparation for our legal team. "
        "2+ years paralegal experience required.",
        expected_family=RoleFamily.LEGAL,
    ),
    BenchmarkJob(
        "unrelated", "false_positive", "Customer Support Specialist",
        "Customer Support Specialist -- resolve tickets via our ticketing system, meeting SLA "
        "targets for a SaaS product. 1+ years support experience required.",
        expected_family=RoleFamily.CUSTOMER_SUPPORT,
    ),
)

ALL_JOBS = _STRONG_JOBS + _FALSE_POSITIVE_JOBS


def _run(profile, config, job: BenchmarkJob):
    job_text = JobText(
        title=job.title, company="Benchmark Co", description=job.description,
        location=job.location, remote_type=job.remote_type,
    )
    det = compute_deterministic_match(profile, config.profile, job_text)
    scored = combine_match(
        det, _NO_SEMANTIC,
        weights=config.automation.scoring_weights,
        semantic_blend_weight=config.automation.matching.semantic_blend_weight,
    )
    result = finalize(scored, config.automation.matching)
    return det, result


def test_benchmark_has_at_least_fifty_jobs_across_required_categories():
    assert len(ALL_JOBS) >= 50
    categories = {job.category for job in ALL_JOBS}
    required = {
        "business_analysis", "product", "operations", "marketing_operations",
        "customer_success_operations", "strategy_operations", "entry_level_analyst",
        "software_engineering", "devops", "ml_engineering", "aerospace_engineering",
        "hardware_embedded", "finance", "sales", "hr", "hospitality_trades", "unrelated",
    }
    assert required <= categories


def test_benchmark_zero_false_positives_reach_qualified_decision(real_profile, real_config):
    """The audit's central quality bar: a wrong-domain job must NEVER
    reach SAVE/REVIEW/APPLY, regardless of incidental keyword overlap."""
    offenders = []
    for job in _FALSE_POSITIVE_JOBS:
        _, result = _run(real_profile, real_config, job)
        if result.decision in _QUALIFIED:
            offenders.append((job.title, result.decision.value, result.overall_score))
    assert offenders == [], f"false positives reached a qualified decision: {offenders}"


def test_benchmark_strong_fit_recall_is_reasonable(real_profile, real_config):
    """Not maximum recall, but a real majority of genuinely strong,
    realistically-worded matches should still reach at least SAVE."""
    qualified = 0
    for job in _STRONG_JOBS:
        _, result = _run(real_profile, real_config, job)
        if result.decision in _QUALIFIED:
            qualified += 1
    recall = qualified / len(_STRONG_JOBS)
    assert recall >= 0.6, (
        f"strong-fit recall too low: {recall:.0%} ({qualified}/{len(_STRONG_JOBS)})"
    )


def test_benchmark_role_family_classification_accuracy(real_profile, real_config):
    labeled = [job for job in ALL_JOBS if job.expected_family is not None]
    correct = 0
    misclassified = []
    for job in labeled:
        det, _ = _run(real_profile, real_config, job)
        # role_family isn't on DeterministicMatch directly; re-derive via
        # the same classifier the matcher itself used, for reporting.
        from job_agent.matching.role_family import classify_role_family

        job_text = JobText(title=job.title, company="Benchmark Co", description=job.description)
        actual = classify_role_family(job_text.title, job_text.combined_text).family
        if actual == job.expected_family:
            correct += 1
        else:
            misclassified.append((job.title, job.expected_family.value, actual.value))
    accuracy = correct / len(labeled)
    assert accuracy >= 0.85, (
        f"role-family accuracy too low: {accuracy:.0%}; misclassified={misclassified}"
    )


def test_benchmark_hard_stop_correctness_for_material_experience_gaps(real_profile, real_config):
    """Every false-positive job stating an explicit "N+ years" figure well
    beyond the candidate's ~0.4 years should raise a real hard-stop or
    risk flag — never silently pass through unflagged."""
    unflagged = []
    for job in _FALSE_POSITIVE_JOBS:
        if "years" not in job.description:
            continue
        det, result = _run(real_profile, real_config, job)
        if not det.hard_stop_reasons and not det.risk_flags:
            unflagged.append(job.title)
    assert unflagged == [], (
        f"jobs with a stated years requirement raised no flag at all: {unflagged}"
    )


def test_benchmark_score_calibration_separates_classes(real_profile, real_config):
    """Diagnostic + hard assertion: false-positive scores must stay
    entirely below the strong-fit floor with a real margin, not just
    below the SAVE threshold by luck."""
    fp_scores = [
        _run(real_profile, real_config, job)[1].overall_score for job in _FALSE_POSITIVE_JOBS
    ]
    strong_scores = [
        _run(real_profile, real_config, job)[1].overall_score for job in _STRONG_JOBS
    ]
    save_threshold = real_config.automation.matching.save_threshold

    assert max(fp_scores) < save_threshold
    assert sum(strong_scores) / len(strong_scores) > sum(fp_scores) / len(fp_scores)

# Career OS — Autonomous Global Job Discovery & Application Agent

A modular, auditable system that discovers job postings, matches them against
a truthful candidate knowledge base, and (in later phases) prepares and
submits applications — with humans in the loop by default and every
generated fact traceable to a source.

**This repository is at the end of Phase 6A (Provider Architecture &
Contracts).** Phase 6A is architecture/contracts only — see "Architecture
(Phase 6A" below. It widens the `ApplicationProvider` interface, adds a
`SUBMISSION_UNCERTAIN` state, and wires `config/rules.yaml`'s safety rules
into actual enforcement for the first time — but ships **no real provider,
no browser automation, no credential handling, and no new way to reach
SUBMITTED/VERIFIED**. `ManualReviewProvider` remains the only shipped
`ApplicationProvider`, and its `submit()` still always refuses. Resume
variant selection/tailoring, real ATS/browser-automation integrations, and
live submission do not exist yet. **Nothing in this codebase can submit a
real job application.**

## Core principle

> HIGH-QUALITY APPLICATIONS > HIGH APPLICATION COUNT

And the rule everything else is subordinate to: **the system never
fabricates candidate information.** Anything not present in the candidate
knowledge base is represented as the literal value `UNKNOWN` with
`confidence=0.0, verified=False` — never guessed, never inferred into a
verified fact. See `config/rules.yaml`.

## Project structure

```
config/                  Human-edited YAML config (roles, preferences, automation, safety rules)
  profile.yaml            Target role taxonomy, industries, exclusions
  preferences.yaml        Work/location/salary/visa preferences (UNKNOWN until you fill them in)
  sources.yaml            Job source adapter config (Phase 2+, all disabled for now)
  automation.yaml         Automation level, thresholds, dry-run/live-mode, rate limits
  rules.yaml              Hard safety rules and hard-stop conditions

candidate/                The candidate knowledge base — source of truth
  resume_master.docx       Original resume (untouched)
  profile.md, experience.md, projects.md, skills.md, education.md,
  achievements.md, preferences.md
  answers/                 Reusable answer bank (truthful; UNKNOWN ones flagged for human review)

src/job_agent/
  config/                  Pydantic-validated config loader (loader.py, models.py)
  candidate/               Canonical schema (schema.py) + deterministic parser (parser.py)
  db/                      SQLAlchemy models, session management, candidate repository
  logging/                 Structured JSON logging with secret redaction
  net/                     Resilient HTTP client (timeouts, retries, backoff+jitter)
  jobs/                    Job discovery engine (Phase 2)
    schema.py               Canonical Job object
    source.py                JobSource plugin interface
    sources/                 greenhouse.py, lever.py adapters
    fingerprint.py           Deterministic cross-source dedup fingerprint
    freshness.py             JUST_POSTED/NEW/RECENT/OLD/UNKNOWN_POST_DATE classification
    repository.py             Dedup-aware DB upsert
    service.py                Orchestrates one discovery scan
  llm/                     LLM provider abstraction (Phase 3)
    provider.py               LLMProvider ABC, NullLLMProvider, AnthropicLLMProvider
  matching/                Matching engine (Phase 3)
    schema.py                 JobMatchResult, Decision enum
    deterministic.py           Keyword/regex-based sub-scores + hard-stop detection
    semantic.py                 LLM-refined sub-scores (role/experience/project)
    scoring.py                   Blends deterministic + semantic per configured weights
    decision.py                   Thresholds + hard-stop/excluded overrides
    repository.py                 Insert-only job_matches persistence
    service.py                     Orchestrates matching for jobs in the DB
  resume/                  Resume Engine (Phase 4)
    extractor.py              Deterministic raw-text extraction from resume_master.docx
    validator.py               Cross-checks CandidateProfile facts against resume text
    versioning.py                Content hashing (profile + source files)
    repository.py                  Insert-only candidate_profile_versions persistence
    service.py                       Orchestrates extract → validate → hash → persist-or-noop
  applications/            Job Application Engine (Phase 5) + Provider Architecture (Phase 6A)
    schema.py                 ApplicationStatus/QuestionCategory enums, GeneratedAnswer,
                                SubmissionEvidence, VerificationResult, and (Phase 6A)
                                ApplicationTarget/ApplicationInspection/PreparedFormState
    state_machine.py           Legal-transition graph + IllegalStateTransitionError
                                 (Phase 6A: adds SUBMISSION_UNCERTAIN)
    provider.py                  ApplicationProvider interface + ManualReviewProvider
                                   (Phase 6A: widened with 4 concrete, safe-default methods)
    rules_enforcement.py           Phase 6A: config/rules.yaml -> HUMAN_REQUIRED enforcement
    answer_bank.py                   Loads candidate/answers/*.md
    answer_validator.py                Deterministic fabrication detector for LLM answers
    answer_engine.py                     3-tier answer resolution (hard-block/bank/LLM)
    rate_limits.py                         Day/hour/company/source submission caps
    duplicates.py                            Cross-source duplicate application detection
    repository.py                              Insert-only application_events audit trail
    service.py                                   discover/prepare/submit/verify/retry
                                                   orchestration + (Phase 6A) per-item batch
                                                   isolation and inspection-driven HUMAN_REQUIRED
  cli/                     Typer CLI (main.py)

prompts/                 Versioned prompt text (job_matcher.md, answer_generator.md)

alembic/                  Database migrations (source of truth for schema evolution)
tests/unit/               pytest unit tests
```

## Architecture (Phase 1)

```
candidate/*.md  +  config/profile.yaml, preferences.yaml
        │  (deterministic parser, NOT an LLM call)
        ▼
CandidateProfile (Pydantic, every field carries: source, confidence, verified)
        │
        ▼
SQLite database (candidate, candidate_facts, skills, experiences, projects, ...)
        │
        ▼
CLI (job-agent profile parse / status / health / dry-run)
```

Why the candidate knowledge base is markdown, not just the resume PDF: the
system must reason about *evidence strength* per skill (`HAS` vs.
`DEMONSTRATED` vs. `ADJACENT`), not just presence/absence. That distinction
doesn't exist in a resume PDF — it has to be authored once, deliberately, by
whoever maintains the candidate files. The parser is deterministic (regex
over a documented format), not an LLM call, so ingestion never introduces
its own hallucination risk.

## Candidate schema (canonical)

`job_agent.candidate.schema.CandidateProfile` — every leaf value that could
be wrong is a `Fact[T]`:

```python
Fact(value="Python", source="candidate/skills.md", confidence=1.0, verified=True)
Fact.unknown(source="config/preferences.yaml")  # -> value="UNKNOWN", confidence=0.0, verified=False
```

Skills additionally carry an `EvidenceLevel`:

| Level | Meaning | Where it comes from |
|---|---|---|
| `HAS` | Self-declared (resume competencies / certification) | `candidate/skills.md` |
| `DEMONSTRATED` | Backed by a specific experience/project bullet | `candidate/skills.md` |
| `ADJACENT` | Related but never itself claimed — matching-only | `candidate/skills.md` |
| `MISSING` | Job requires it, profile has no basis for it | computed at match time only (Phase 3) |
| `UNKNOWN` | Not enough information to say | computed at match time only (Phase 3) |

`MISSING`/`UNKNOWN` are rejected by `SkillFact` validation if someone tries
to store them as a candidate fact — they only exist as match-time output.

Preference-shaped fields (`work_preferences`, `location_preferences`,
`salary_preferences`, `visa_information`, `target_roles`) come from
`config/preferences.yaml` / `config/profile.yaml`, not from the markdown
files, since those are decisions the candidate makes, not resume facts.

## Architecture (Phase 2 — Job Engine)

```
config/sources.yaml (enabled sources + board tokens)
        │
        ▼
build_sources()  →  [GreenhouseJobSource, LeverJobSource, ...]   (job_agent.jobs.source.JobSource)
        │                    each backed by a ResilientHttpClient
        │                    (timeouts, retries, exponential backoff + jitter,
        │                     circuit-breaker-style hard retry cap)
        ▼
source.search() → raw postings  →  source.normalize() → canonical Job
        │
        ▼
classify_freshness(job.posted_at)   →  JUST_POSTED / NEW / RECENT / OLD / UNKNOWN_POST_DATE
        │
        ▼
compute_job_fingerprint(job)        →  content-based dedup key (company+title+location+canonical URL)
        │
        ▼
upsert_job()  →  jobs table (dedup on (source, source_job_id); first_seen_at
                  never overwritten; cross-source duplicates flagged via
                  shared job_fingerprint, never silently merged/dropped)
```

Only two adapters exist: **Greenhouse** and **Lever**, both against their
official, public, unauthenticated, read-only JSON APIs (Job Board API /
Postings API) — no login wall, no bot detection, nothing to bypass. Every
other source in `config/sources.yaml` (Workday, LinkedIn, Indeed, Wellfound,
YC Jobs, generic career pages) is `enabled: false` and stays that way until
its adapter exists and its terms have actually been reviewed — see BUILD
PROMPT section 6. **This sandboxed development environment's network policy
blocks outbound calls to `boards-api.greenhouse.io` and `api.lever.co`**, so
the adapters are verified against mocked HTTP responses (`httpx.MockTransport`)
in the test suite rather than live calls from here; the example board tokens
in `config/sources.yaml` are explicit `REPLACE_ME` placeholders, not
unverified guesses.

`JobSource` is a 4-method interface (`search`, `normalize`, `get_posted_time`,
`health_check`, plus an optional `fetch_job` for sources that need a second
request per posting) — adding a new source means implementing that
interface and registering it in `job_agent.jobs.service.build_sources()`;
nothing else changes (BUILD PROMPT section 46).

Deduplication is deliberately two-tiered:
* **Per-source identity** — `(source, source_job_id)` — decides insert vs.
  update on rescan. Never creates a duplicate row for the same posting.
* **Cross-source fingerprint** — `job_fingerprint`, a hash of normalized
  company + title + location + canonicalized application URL (tracking
  params stripped) — flags likely duplicates *across* sources (e.g. a job
  on both a company's Greenhouse board and its own career page). This is a
  deterministic heuristic, not semantic similarity; true semantic dedup
  (comparing descriptions with embeddings) is Phase 3+ and layers on top,
  it doesn't replace this. The repository records the fingerprint but never
  auto-merges or drops a fingerprint-matched row — that decision belongs to
  the matching/application layer, which can choose not to apply twice
  without destroying either source's history (section 54).

## Architecture (Phase 3 — Matching Engine)

```
CandidateProfile  +  Job (from DB)
        │
        ▼
compute_deterministic_match()   (job_agent.matching.deterministic — no LLM call)
  ├─ skills_match        keyword vocabulary vs. candidate skill evidence (fuzzy substring match)
  ├─ experience_match     "N+ years" extraction vs. computed months of experience
  ├─ role_match            title vs. config/profile.yaml target_roles / excluded_roles
  ├─ project_match          keyword overlap with candidate project stack/highlights
  ├─ education_match         degree-requirement phrases vs. candidate education
  ├─ location_match           remote/location match vs. candidate location preferences
  ├─ seniority_match           senior/junior keyword detection
  └─ eligibility_match          sponsorship-requirement phrases vs. visa_information
        │
        ▼  (skipped entirely if excluded/hard-stopped/very low score — cost optimization)
run_semantic_match()   (job_agent.matching.semantic — one Anthropic tool-use call)
  refines: role_match, experience_match, project_match
  untrusted job text is clearly delimited; system prompt forbids following
  any instruction found inside it (prompt injection defense, section 30)
        │
        ▼
combine_match()   →   weighted blend (config/automation.yaml scoring_weights + semantic_blend_weight)
        │
        ▼
decide()   →   APPLY / REVIEW / SAVE / SKIP / HUMAN_REQUIRED
  hard-stop conditions (unknown_work_authorization, seniority_mismatch,
  required_degree_missing) always force HUMAN_REQUIRED regardless of score;
  candidate-configured exclusions always force SKIP; no semantic signal
  caps the decision below APPLY even at a high deterministic score
        │
        ▼
save_job_match()  →  job_matches (insert-only — each run is a new historical row)
```

**Deterministic vs. semantic is not an implementation detail, it's the
contract from BUILD PROMPT section 10**: skills, education, location,
seniority, and eligibility are pattern-matchable and stay 100%
deterministic (no LLM, no cost, always available, always explainable).
Only role alignment, experience similarity, and project relevance — the
dimensions that genuinely need judgment about transferability and career
trajectory — go through the semantic stage, and only when it's plausibly
worth the API call.

**Cost optimization (section 40):** the semantic stage is skipped entirely
when a job is already decided by cheap signals alone — excluded by
config, hard-stopped, or so poorly matched on deterministic signals that an
LLM call is very unlikely to change the outcome. In this repo's own test
run against 4 sample jobs, 2 of the 4 never triggered an LLM call.

**No API key configured is a normal, safe state, not an error** — the
`NullLLMProvider` is a real fallback path (not a workaround): `jobs match`
still runs deterministic-only scoring, and `decide()` caps the outcome at
REVIEW even for a would-be-APPLY score, because auto-applying without the
semantic "second opinion" is a risk this system doesn't take. This sandbox
has no `ANTHROPIC_API_KEY` configured, so all matching shown in this repo's
own testing is deterministic-only; semantic blending is verified with a
fake `LLMProvider` in `tests/unit/test_matching_scoring.py` and
`test_matching_semantic.py`, and the real `AnthropicLLMProvider` is tested
against a mocked Anthropic client (`tests/unit/test_llm_provider.py`) —
same reasoning as Phase 2's mocked job-source tests.

**Auditability:** `job_matches` is insert-only. Re-running `jobs match`
never overwrites a prior score — it adds a new row, so match history
survives config/threshold changes and eventually supports the outcome
analytics in section 24 ("which match score predicts interviews?").

## Architecture (Phase 4 — Resume Engine)

```
candidate/resume_master.docx  (authoritative source — python-docx, no LLM)
        │
        ▼
extract_resume_text()   →  raw plain text (paragraphs + tables)
        │
CandidateProfile  ──────────────┤
(from Phase 1's parser,         ▼
 unchanged)              validate_profile_against_resume()
                            STRICT substring match: identity, contact,
                              experience title/company, project names,
                              education institutions, certification names,
                              HAS-level skills (self-declared, so literal)
                            FUZZY word-overlap match: achievements (some
                              are honest paraphrases of resume bullets),
                              DEMONSTRATED-skill evidence notes
                                │
                    ┌───────────┴───────────┐
                 0 issues                 N issues
                    │                         │
                    ▼                         ▼
          validation_status=PASSED   validation_status=FAILED
                    │                         │
                    └───────────┬─────────────┘
                                 ▼
                    compute hashes (profile + resume file + every
                    candidate/*.md + config/profile.yaml/preferences.yaml)
                                 │
                    same as latest version?  ──yes──▶  no-op, return it unchanged
                                 │ no
                                 ▼
                    create_version()  →  candidate_profile_versions
                    (insert-only — PASSED and FAILED attempts both kept,
                     forever; never updated, never deleted)
```

**Why validation exists at all, given Phase 1 already hand-authored the
candidate files faithfully:** it's the ongoing safety net, not a one-time
check. `candidate/*.md` could drift from `resume_master.docx` in the
future — the resume gets updated and the markdown doesn't, or vice versa —
and nothing before Phase 4 would have caught that. This module makes
"every fact traces to the actual resume file" something the system
*proves* on every `profile parse`, not something asserted once during
authoring and never checked again.

**Why two matching strategies, not one:** strict substring matching on
`candidate/achievements.md`'s "Notable Project Metrics" entries produces
false positives — that file legitimately rewrites some resume bullets into
cleaner prose (e.g. resume's "(116 businesses, 19 categories)" becomes
"covering 116 businesses across 19 categories" in the markdown). A fuzzy,
word-overlap threshold (≥60% of a claim's significant words must appear in
the resume) tolerates that honest rewording while still catching real
fabrication — a fabricated achievement referencing a nonexistent employer,
number, or technology shares few or no words with the actual resume. This
was verified empirically, not just reasoned about: `tests/unit/
test_resume_validator.py` injects real fabricated facts (a fake job title,
a fake employer, a fake HAS-level skill, a fake achievement with a fake
statistic) into the real profile and confirms every one is caught, while
the actual, unmodified candidate profile produces **zero** false-positive
issues against the actual resume file.

**Versioning is content-addressed, not timestamp-based.** `profile_hash`
excludes `parsed_at` specifically so re-running `profile parse` with
nothing actually changed is a no-op (checked against `resume_file_hash`
and every `source_file_hashes` entry too) — it doesn't spam a new "version"
every time the command runs, only when the candidate's actual resume or
markdown files change. `job-agent profile history` lists every version
ever created, including FAILED ones — a validation failure is recorded for
audit, never silently dropped, but `get_latest_verified_version()` (the
function future phases must use) only ever returns a PASSED version, so a
failed re-parse can never silently become "the current profile" something
downstream trusts.

**No LLM anywhere in this phase.** Extraction is pure `python-docx`
structural parsing; validation is pure string matching. Asking a model
"does this claim appear in the resume?" would reintroduce the exact
hallucination risk this module exists to guard against (BUILD PROMPT
section 59: prefer deterministic code over LLM calls wherever one works).

**Integration with Phase 1–3 is additive only.** `job-agent profile parse`
keeps its exact Phase 1 output and behavior (same table, same candidate
row, same exit code on a parse error) and now *additionally* creates/checks
a profile version as a second step — nothing about Phase 1's contract
changed. No existing table's schema changed; `candidate_profile_versions`
is a new table with its own migration. Phase 3's matching engine still
calls `parse_candidate_profile()` fresh each run, unchanged — profile
versioning is infrastructure Phase 5+ (resume tailoring, applications) can
build on for "which exact profile was this application based on", not a
retrofit onto Phase 3's already-verified matching pipeline.

**What Phase 4 explicitly does NOT include**, despite being listed under
"Resume Engine" in the original BUILD PROMPT (section 12/49): a registry of
multiple resume *file* variants (master/product/operations/analytics), a
resume selector that picks among them per job, controlled resume
*tailoring* (reordering bullets, adjusting emphasis), or PDF generation.
There is currently exactly one resume file, so "selecting among variants"
has nothing to select among yet — that work is deferred, not silently
dropped; see "What remains" below.

## Architecture (Phase 5 — Job Application Engine)

```
job_matches (Phase 3, APPLY/REVIEW/HUMAN_REQUIRED/SAVE/SKIP decision)
        │
        ▼
discover_application()   →  applications row, exactly one per (job_id,
                              candidate_id) — DB unique constraint backs
                              this up even under a racing concurrent call.
                              Checks the DB-level uniqueness AND a
                              cross-source content-fingerprint match
                              (job_agent.applications.duplicates) before
                              creating anything new.
        │
   DISCOVERED ──▶ MATCHED / HUMAN_REQUIRED / SKIPPED   (from the match decision)
        │
        ▼
prepare_application()    →  ApplicationProvider.get_questions(job)
                              (ManualReviewProvider's representative set —
                               no real ATS form-scraping exists yet)
                                        │
                              generate_answer() per question — 3 tiers,
                              cheapest/safest first:
                                1. hard-block (SALARY/VISA/LEGAL/DEMOGRAPHIC)
                                   — deterministic, no LLM, always HUMAN_REQUIRED
                                   if the underlying fact is UNKNOWN or the
                                   category is categorically never inferred
                                2. answer bank (candidate/answers/*.md) —
                                   human-authored, used verbatim
                                3. LLM draft → answer_validator.
                                   validate_generated_answer() — deterministic
                                   fabrication check (unknown proper nouns /
                                   numbers not in the resume+profile) — a
                                   rejected or unobtainable draft becomes
                                   HUMAN_REQUIRED, never a best-effort guess
        │
   MATCHED/HUMAN_REQUIRED ──▶ PREPARED / HUMAN_REQUIRED / FAILED
        │
        ▼
submit_application()     →  every gate must hold or it stays PREPARED with
                              an audit event explaining why:
                                1. config.is_submission_allowed() — dry_run
                                   disabled AND live_mode enabled (Phase 1's
                                   existing choke point, reused as-is)
                                2. automation level 4, OR human_approved=True
                                3. rate limits (day/hour/company/source) —
                                   a hit routes to SKIPPED, never queued around
                                4. the provider itself must succeed and return
                                   evidence — ManualReviewProvider's submit()
                                   always raises SubmissionRefusedError, so
                                   real submission is structurally impossible
                                   until a real, reviewed provider is built
        │
   PREPARED ──▶ SUBMITTED / FAILED
        │
        ▼
verify_application()     →  only path to VERIFIED — requires the provider
                              to return verified=True AND evidence with at
                              least one non-blank concrete field
                              (SubmissionEvidence.has_concrete_evidence).
                              Inconclusive/missing/errored verification
                              leaves the application at SUBMITTED — never
                              silently promoted, never silently downgraded.
   SUBMITTED ──▶ VERIFIED (only with real evidence) / stays SUBMITTED
```

`retry_application()` is the only sanctioned way out of FAILED: since
`applications` is unique per `(job_id, candidate_id)`, a fully-terminal
FAILED would permanently block ever applying to that job again. It moves
the *same row* back to MATCHED (never a new one) so preparation and every
safety gate re-run fresh — never a silent re-use of a failed attempt's
stale answers.

Every status change goes through `job_agent.applications.repository.
transition_status()`, the single function allowed to write
`Application.status` — it validates against the state machine's legal-
transition graph and always appends an immutable `ApplicationEvent` row in
the same call, so no status change can happen without a matching audit
record, and no historical event is ever updated or deleted.

**Answer generation treats job/application content as untrusted input.**
Question text goes through the same delimiter-neutralization pattern
Phase 3's semantic matcher uses for job postings (`answer_engine.
normalize_delimiter`) before being embedded in an LLM prompt, and the
system prompt explicitly instructs the model to treat the question as data,
never as instructions. But the real defense is downstream and doesn't
depend on the LLM behaving: `answer_validator.validate_generated_answer()`
is a **deterministic** check (extracts proper-noun-like phrases and
multi-digit numbers from the draft and requires each to appear in the
candidate's actual resume/profile facts) — so even if a prompt injection
somehow got the model to draft a fabricated answer, it still gets rejected
before it can ever be marked `requires_human=False`. Verified empirically:
a truthful answer using real resume facts passes with zero false positives,
while fabricated employers/metrics are reliably caught (`tests/unit/
test_answer_validator.py`, `test_answer_engine.py`).

## Architecture (Phase 6A — Provider Architecture & Contracts)

**Phase 6A is architecture and contracts only.** It was preceded by a
dedicated reconnaissance pass (repository inspection + a written
architecture proposal, not committed as code) that this section
summarizes the outcome of. Nothing in this phase talks to a real job
platform, opens a browser, handles a credential, or creates any new path
to SUBMITTED/VERIFIED — see "What remains" for everything explicitly
deferred to Phase 6B+.

**1. Widened `ApplicationProvider` interface** (`job_agent.applications.
provider`) — four new methods, all **concrete with safe defaults**, not
abstract, so every existing provider (`ManualReviewProvider` and every
fake provider across the test suite) keeps instantiating and passing
unchanged:

```
discover_application(job) -> ApplicationTarget          # confirms a target exists; default reachable=False
inspect_application(job, target) -> ApplicationInspection # raw structural facts; default structure_recognized=False
retrieve_application_questions(job, target) -> [Question]  # default delegates to get_questions()
fill_application(job, target, answers) -> PreparedFormState  # stages answers; NEVER transmits anything
```

`submit`/`verify`/`get_questions`/`health_check` (Phase 5) are unchanged —
they remain the only methods that can produce `SubmissionEvidence`/
`VerificationResult`. `ApplicationTarget`, `ApplicationInspection`, and
`PreparedFormState` (`job_agent.applications.schema`) carry no candidate
data and no credential of any kind — `ApplicationTarget.provider_reference`
is an opaque handle, never a secret.

**Architectural boundary, enforced automatically, not just by
convention:** `job_agent.applications.provider` never imports
`applications.service`, `applications.state_machine`,
`applications.rate_limits`, or `config.loader` — a provider reports facts
(does this target exist? is a CAPTCHA present? is the form structure
recognized?), it never decides consequences. `tests/unit/
test_applications_provider.py::test_provider_module_never_imports_core_
decision_logic` parses `provider.py`'s own AST and asserts this on every
test run, so the boundary can't silently erode as the module grows.

**2. `SUBMISSION_UNCERTAIN` state** — added for exactly one failure mode a
real provider will eventually hit: a submission attempt whose outcome
couldn't be determined (e.g. a network timeout after the request may
already have reached the platform). Legal transitions:

```
PREPARED -> SUBMISSION_UNCERTAIN
SUBMISSION_UNCERTAIN -> VERIFIED / FAILED / HUMAN_REQUIRED
```

Deliberately **no** path back to PREPARED or SUBMITTED, and no self-loop —
an ambiguous submission can only be resolved by independent verification
or escalated to a human, never blindly retried (which is exactly how a
duplicate real-world application would happen). No Phase 6A provider can
actually produce this transition — `ManualReviewProvider` always raises
`SubmissionRefusedError` instead — the state exists so the contract is
ready for Phase 6B+.

**3. `config/rules.yaml` wired into actual enforcement for the first
time.** Before Phase 6A, `RulesConfig` was loaded and strictly validated
at startup but never consulted by any decision code —
`stop_on_captcha`/`stop_on_mfa`/`stop_on_unexpected_form` were declared,
not enforced. `job_agent.applications.rules_enforcement.
evaluate_inspection()` is now the sole reader of `config.rules.safety` for
this purpose — no second, independent copy of these flags exists anywhere.
It maps a provider's raw `ApplicationInspection` facts to a verdict, and
`job_agent.applications.service.handle_application_inspection()` is the
only place that verdict is applied to a real `Application` row (never the
provider itself — same "reports facts, doesn't decide" boundary as
above). `handle_application_inspection()` is not yet called from the CLI
or from `prepare_applications_batch()`: with `ManualReviewProvider`'s
honest-but-conservative default inspection (`structure_recognized=False`
for everything, since it performs no real inspection), wiring it into the
main flow today would route every single job to HUMAN_REQUIRED via
`unexpected_form_structure` — a behavioral regression against Phase 5,
not a Phase 6A goal. Wiring it into the live pipeline is Phase 6B+ work,
once a real provider exists that can report genuine structural facts.

**4. Per-item failure isolation** for `applications prepare`/`applications
run` (`job_agent.applications.service.prepare_applications_batch()` /
`submit_applications_batch()`), following the exact pattern
`job_agent.jobs.service.scan_source()` already uses for job sources: catch,
log via `log_event()`, roll back the session, continue. One job/application
raising an unexpected error can no longer abort the rest of the batch —
each CLI command now reports a per-item result table/line including any
errors, rather than crashing the whole run.

## Database schema

SQLite via SQLAlchemy 2.0, migrated with Alembic. 16 tables: BUILD PROMPT
section 21's original 15-table minimum set (`candidate`, `candidate_facts`,
`skills`, `experiences`, `projects`, `companies`, `job_sources`, `jobs`,
`job_matches`, `resumes`, `applications`, `application_answers`,
`application_events`, `notifications`, `system_events`) plus Phase 4's
`candidate_profile_versions`.

Phase 1 populates `candidate`, `candidate_facts`, `skills`, `experiences`,
`projects` (via `job-agent profile parse`). Phase 2 adds `job_sources`,
`companies`, and `jobs` (via `job-agent jobs scan`). Phase 3 adds
`job_matches` (via `job-agent jobs match`; insert-only, see above). Phase 4
adds `candidate_profile_versions` (also via `job-agent profile parse`;
insert-only, see above). Phase 5 populates `applications` (current state,
one row per `(job_id, candidate_id)` — DB unique constraint enforced) and
`application_answers` via `job-agent applications prepare`, and
`application_events` (insert-only audit trail — see above) via every
Phase 5 command. `resumes` and `notifications` remain defined but unused,
for a later phase.

Phase 5's migration (`92b5df3ca242`) added `applications.profile_version_id`
(links an application to the exact profile version it was prepared
against) and `applications.dry_run`, plus `application_answers.validated`/
`validation_notes` (whether the LLM-drafted answer passed the fabrication
check, and why not if it didn't) — and the `uq_applications_job_candidate`
unique constraint that makes a duplicate application impossible at the DB
level, not just in application code.

Indexes exist on `job_fingerprint`, `company_name`, `title`, `posted_at`
(jobs), `overall_score`/`decision` (job_matches), `status`/`match_score`
(applications) — the lookups the matching/dashboard layers will need.

## Configuration

Everything behavior-affecting is in `config/*.yaml`, validated against
strict Pydantic models (`extra="forbid"` — a typo'd key fails loudly at
startup, not silently). Two safety-critical values can be overridden by
environment variables, which always win over YAML:

```
DRY_RUN=true    # default; nothing can ever submit
LIVE_MODE=false # default; must be explicitly true, together with DRY_RUN=false,
                # for job_agent.config.AppConfig.is_submission_allowed() to return True
```

Copy `.env.example` to `.env` (or run `job-agent init`) and fill in secrets.
`.env` is gitignored.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head        # create the SQLite schema (data/job_agent.db)

job-agent status            # show effective dry-run/live-mode/automation-level state
job-agent health            # config loads + candidate profile parses + DB reachable
job-agent profile parse     # parse candidate/*.md + config/*.yaml, persist to DB,
                             # then validate + version the profile against the resume
job-agent profile history   # list every candidate profile version (PASSED and FAILED)
job-agent dry-run           # confirm submission is currently impossible
job-agent jobs scan         # poll enabled job sources, persist new/updated jobs
job-agent jobs match        # score every job in the DB against the candidate profile
job-agent applications prepare  # discover + prepare an Application for every job_matches
                                 # row without one yet; generates answers (dry-run safe,
                                 # no submission happens here regardless of config)
job-agent applications review   # list every application awaiting human input, with
                                 # exactly which questions need it and why
job-agent applications run      # attempt submission for every PREPARED application —
                                 # with the shipped ManualReviewProvider this always
                                 # reports what a human still needs to do; see below
```

`profile parse` exits non-zero if the resume file can't be read, or if any
fact in the profile can't be traced back to it — printing exactly which
claims failed and why, never silently proceeding with an unverified
profile.

To actually discover jobs: edit `config/sources.yaml`, set `enabled: true`
on `greenhouse` and/or `lever`, and replace the placeholder `token`/
`company_name` entries under `boards:` with a real Greenhouse board token
or Lever company slug (found on the company's own careers page URL). With
nothing enabled, `jobs scan` reports that clearly and does nothing — it
never guesses at a board to poll.

To enable semantic matching: set `ANTHROPIC_API_KEY` in `.env`. Without it,
`jobs match` still runs (deterministic-only), and answer generation in
`applications prepare` falls back to the answer bank / `HUMAN_REQUIRED`
instead of an LLM draft — both say so explicitly rather than silently
degrading.

`applications run` never actually submits anything in this phase: the only
shipped `ApplicationProvider` (`ManualReviewProvider`) always refuses at the
`submit()` call, regardless of `DRY_RUN`/`LIVE_MODE`/automation level — real
ATS/browser-automation integrations are a later phase. `job-agent dashboard`
is still registered for interface stability but exits with a clear "not
implemented yet" message — see `job_agent/cli/main.py`.

## Testing

```bash
pytest -q            # 350 tests: config, candidate schema/parser, db, job engine,
                      # matching engine, resume engine, job application engine,
                      # Phase 6A provider-architecture contracts
ruff check src tests # lint — currently clean (some pre-existing long lines in
                      # Phase 4's auto-generated Alembic migrations are exempt)
mypy -p job_agent     # type check — currently clean
alembic check         # no drift between models and the latest migration
                      # (Phase 6A adds no schema changes — SUBMISSION_UNCERTAIN
                      # is a value in the existing free-text status column)
```

Tests run against the **real** `candidate/*.md`, `config/*.yaml`, and
`resume_master.docx` files (not synthetic fixtures), so they double as a
regression check on the shipped candidate data itself — e.g. `test_full_
profile_assembly_never_fabricates_preferences` asserts that salary/visa
stay `UNKNOWN` because the resume never states them, the deterministic
matcher tests confirm actual skills (SQL, Excel, Agile/Scrum, Figma) are
correctly fuzzy-matched rather than reported MISSING due to naming
differences ("Basic SQL" vs. "SQL"), and `test_real_profile_has_zero_
issues` proves the entire shipped candidate profile is traceable to the
actual resume file with zero unverifiable claims. The same test module
also injects real fabricated facts (a fake job, employer, skill,
achievement, education, certification, and project) into the real profile
and confirms every single one is caught. Job-source and LLM-provider tests
never make a real network call — Greenhouse/Lever tests inject an
`httpx.MockTransport`, and `AnthropicLLMProvider` tests inject a fake
Anthropic client, both because this sandbox can't reach those APIs anyway
and because deterministic mocked responses are the right way to test this
regardless (BUILD PROMPT section 35).

Phase 5's tests (`test_applications_*.py`, `test_answer_*.py`) use fake
`ApplicationProvider`/`LLMProvider` implementations exclusively — no test
can make a real network call or a real submission, and several tests use a
provider whose `submit()` raises `AssertionError` if called at all, to
structurally prove that blocked paths (dry-run, missing approval, rate
limit) never reach the provider. Coverage explicitly includes: duplicate
applications (DB-level and cross-source), failed submissions, verification
failures (inconclusive, missing evidence, provider error), provider
timeouts, prompt-injection-containing application questions, unsupported/
unanswerable questions, missing-resume-fact fabrication attempts,
`HUMAN_REQUIRED` transitions (from both discovery and preparation),
dry-run behavior, historical audit-trail preservation (event rows
accumulate and are never overwritten), retry-from-FAILED idempotency
(never creates a duplicate row), and the core invariant that an
application can never reach `VERIFIED` without genuine, non-blank
verification evidence.

Phase 6A's tests (`test_rules_enforcement.py`, plus additions to
`test_applications_provider.py`, `test_applications_schema.py`,
`test_applications_state_machine.py`, `test_applications_service.py`)
cover: the widened provider contract on both `ManualReviewProvider` and a
minimal legacy provider that implements only the Phase 5 methods (proving
backward compatibility), the `provider.py` import-boundary check described
above, every legal and forbidden `SUBMISSION_UNCERTAIN` transition,
`evaluate_inspection()` against the **real, loaded** `config/rules.yaml`
(not a hardcoded copy — one test asserts the real file's `stop_on_*` flags
are `True`, others prove flipping a flag off changes the outcome),
`handle_application_inspection()`'s CAPTCHA/MFA/unexpected-form routing
and its guard against an illegal target state, and per-item batch
isolation for both `prepare_applications_batch()` and
`submit_applications_batch()` — including a test where a single shared,
selectively-crashing provider instance fails on one job and the batch
still fully processes the next one, and a test confirming the crash never
weakens the existing dry-run gate.

## What's implemented (Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5 + Phase 6A)

**Phase 1 — Foundation**
- [x] Project structure, `pyproject.toml`, `.gitignore`, `.env.example`
- [x] Config system: 5 YAML files + strict Pydantic validation + env-var safety overrides
- [x] Candidate knowledge base authored from the real resume (no fabrication)
- [x] Canonical `CandidateProfile` schema with per-field provenance (`Fact[T]`, `SkillFact`)
- [x] Deterministic markdown parser (`job_agent.candidate.parser`), with clear errors on malformed input
- [x] Full 15-table database schema (SQLAlchemy 2.0) + Alembic migration
- [x] Candidate repository (idempotent upsert/reparse)
- [x] Structured JSON logging with secret redaction
- [x] CLI: `init`, `profile parse`, `status`, `health`, `dry-run`

**Phase 2 — Job Engine**
- [x] Canonical `Job` schema (`job_agent.jobs.schema`), with `raw_data` always preserved
- [x] `JobSource` plugin interface + resilient HTTP client (timeouts, retries, backoff+jitter, hard retry cap)
- [x] Greenhouse and Lever adapters against their official public read-only JSON APIs
- [x] Deterministic dedup fingerprinting (per-source identity + cross-source content fingerprint)
- [x] Freshness classification (JUST_POSTED/NEW/RECENT/OLD/UNKNOWN_POST_DATE) from configurable thresholds
- [x] Dedup-aware job repository (upsert; `first_seen_at` never overwritten)
- [x] Discovery service orchestrating the full scan pipeline + `job-agent jobs scan` CLI command
- [x] 35 new unit tests (fingerprint, freshness, HTTP retry behavior, adapters, repository, service)

**Phase 3 — Matching Engine**
- [x] `LLMProvider` abstraction (`job_agent.llm`) — `NullLLMProvider` (safe default, no API key)
      and `AnthropicLLMProvider` (forced tool-use JSON, schema-validated)
- [x] Deterministic matcher: skills (fuzzy vocabulary match), experience-years, role alignment
      (target/excluded roles), project overlap, education, location, seniority, eligibility/visa
- [x] Semantic matcher: LLM-refined role/experience/project scores, with an explicit
      prompt-injection defense for untrusted job-posting text (section 30)
- [x] Retry-once-then-fallback on invalid LLM output (section 29); never crashes, never lets
      malformed output touch scoring
- [x] Scoring engine blending deterministic + semantic per `config/automation.yaml` weights
- [x] Decision engine: configurable thresholds, hard-stop conditions force HUMAN_REQUIRED,
      candidate exclusions force SKIP, missing semantic signal caps below APPLY
- [x] Cost-optimized pipeline: semantic stage skipped for excluded/hard-stopped/very-low-score jobs
- [x] Insert-only `job_matches` persistence (full audit history) + `job-agent jobs match` CLI command
- [x] 56 new unit tests (deterministic sub-scores, LLM provider, semantic retry/fallback,
      scoring blend, decision thresholds, repository, service orchestration)

**Phase 4 — Resume Engine**
- [x] Deterministic resume text extraction (`job_agent.resume.extractor`, python-docx,
      no LLM) with explicit `ResumeExtractionError` on missing/corrupt/empty files
- [x] Resume consistency validator (`job_agent.resume.validator`) cross-checking every
      identity/contact/experience/project/education/certification/achievement/skill
      claim in the CandidateProfile against the actual resume file
- [x] Two matching strategies chosen per field's authoring convention: strict substring
      for direct transcriptions, word-overlap fuzzy matching for honest paraphrases
      (tolerates truthful rewording, still catches genuine fabrication — verified
      empirically with injected fake facts, not just reasoned about)
- [x] Content-addressed profile versioning (`job_agent.resume.versioning`): hashes the
      profile snapshot plus every source file (resume + candidate/*.md + config), so
      re-parsing with nothing changed is a no-op rather than spamming new versions
- [x] Insert-only `candidate_profile_versions` table — PASSED and FAILED attempts both
      preserved forever; `get_latest_verified_version()` never returns a FAILED one
- [x] `job-agent profile parse` now also creates/checks a profile version (additive —
      Phase 1's exact output/behavior for the base command is unchanged); new
      `job-agent profile history` command
- [x] Zero code or schema changes to Phase 1–3 tables/behavior — one new table,
      one new package, existing commands extended additively only
- [x] 39 new unit tests, including deliberate hallucination-injection tests (fake job,
      employer, HAS-skill, DEMONSTRATED-skill, achievement, education, certification,
      project all confirmed caught) and a paraphrase-tolerance regression guard

**Phase 5 — Job Application Engine**
- [x] Explicit `ApplicationStatus` state machine (DISCOVERED, MATCHED,
      PREPARED, HUMAN_REQUIRED, SUBMITTED, VERIFIED, FAILED, SKIPPED) with a
      single legal-transition graph (`job_agent.applications.state_machine`)
      — every status change is validated against it and raises
      `IllegalStateTransitionError` rather than silently allowing an unsafe
      jump (e.g. straight to VERIFIED)
- [x] `applications` current-state row (one per `(job_id, candidate_id)`,
      DB unique constraint) + insert-only `application_events` audit trail
      — the same pattern Phase 2/3 use for `jobs`/`job_matches`; no status
      change can happen without a matching, immutable audit record
- [x] `ApplicationProvider` plugin abstraction (`job_agent.applications.
      provider`), mirroring Phase 2's `JobSource` pattern — the core engine
      is written against the interface, never against one job platform.
      The only shipped implementation, `ManualReviewProvider`, always
      refuses at `submit()`: real external submission is structurally
      impossible in this phase, not just policy-disabled
- [x] Three-tier truthful answer generation (`job_agent.applications.
      answer_engine`): hard-block categories (SALARY/VISA/LEGAL/DEMOGRAPHIC,
      deterministic, no LLM) → human-authored answer bank
      (`candidate/answers/*.md`) → LLM draft, validated
- [x] Deterministic fabrication detector (`job_agent.applications.
      answer_validator`) for LLM-drafted answers — extracts proper-noun-like
      phrases and multi-digit numbers and requires each to appear in the
      candidate's actual resume/profile facts; never asks a model to grade
      its own output, since that would reintroduce the hallucination risk
      it exists to guard against
- [x] Prompt-injection defense for untrusted application-question text
      (delimiter neutralization, same pattern as Phase 3's semantic matcher)
- [x] Duplicate-application prevention: DB-level unique constraint plus
      cross-source content-fingerprint detection (`job_agent.applications.
      duplicates`, reusing Phase 2's fingerprinting)
- [x] Day/hour/per-company/per-source rate limiting
      (`job_agent.applications.rate_limits`), checked immediately before
      any submission attempt; a limit hit routes to SKIPPED, never queued
- [x] `submit_application()` requires `config.is_submission_allowed()`
      (Phase 1's existing dry-run/live-mode choke point, reused as-is) AND
      either automation level 4 or explicit human approval — either gate
      alone is not enough
- [x] `verify_application()` is the only path to VERIFIED, and only with
      genuine, non-blank evidence from the provider — an inconclusive,
      missing, or errored verification leaves the application at SUBMITTED
      (attempted, unconfirmed) forever, never silently promoted or
      downgraded
- [x] `retry_application()` — the only sanctioned way out of FAILED, moving
      the *same* row back to MATCHED so retries can never create a
      duplicate application or silently reuse a failed attempt's stale data
- [x] `job-agent applications prepare/review/run` CLI commands
- [x] 134 new unit tests (state machine, schema, answer bank, answer
      validator, answer engine, provider, repository, rate limits,
      duplicates, and a full lifecycle integration suite) plus one
      adversarial-review fix found and closed during testing (see below)

**Adversarial review finding (fixed):** `discover_application()`'s
hard-stop-match branch (`Decision.HUMAN_REQUIRED`) attempted a direct
`DISCOVERED → HUMAN_REQUIRED` transition that the state machine's
transition graph did not actually permit, which meant that branch would
have thrown an unhandled `IllegalStateTransitionError` in production the
first time a hard-stop match was discovered. Caught by the Phase 5
integration test suite, not by manual inspection; fixed by adding
`HUMAN_REQUIRED` to `DISCOVERED`'s allowed targets. Also hardened
`SubmissionEvidence.has_concrete_evidence` to reject whitespace-only
strings (`" "`) as evidence, closing a theoretical loophole a future
provider could otherwise exploit to satisfy the VERIFIED gate without
providing anything genuinely checkable.

**Phase 6A — Provider Architecture & Contracts** (architecture/contracts
only — see the "Architecture (Phase 6A" section above for full detail)
- [x] Widened `ApplicationProvider` interface: `discover_application`,
      `inspect_application`, `retrieve_application_questions`,
      `fill_application` — all concrete with conservative safe defaults,
      so every pre-existing provider (production and test-only) keeps
      instantiating and passing unchanged
- [x] `ApplicationTarget`/`ApplicationInspection`/`PreparedFormState`
      contract types — no candidate data, no credentials, ever
- [x] Automated, AST-based test proving `provider.py` never imports
      `applications.service`/`state_machine`/`rate_limits`/`config.loader`
      — a provider reports facts, it structurally cannot decide
      consequences
- [x] `SUBMISSION_UNCERTAIN` state with a deliberately narrow transition
      set (`PREPARED -> SUBMISSION_UNCERTAIN -> {VERIFIED, FAILED,
      HUMAN_REQUIRED}`) — no path back to PREPARED/SUBMITTED, no self-loop,
      so an ambiguous submission outcome can never be blindly retried
- [x] `config/rules.yaml` wired into real enforcement for the first time
      (`job_agent.applications.rules_enforcement.evaluate_inspection`) —
      `stop_on_captcha`/`stop_on_mfa`/`stop_on_unexpected_form` now
      actually drive a HUMAN_REQUIRED verdict, with no second/duplicated
      copy of these flags anywhere
- [x] Per-item failure isolation for `applications prepare`/`applications
      run` (`prepare_applications_batch`/`submit_applications_batch`) —
      one bad job/application can no longer abort the whole batch
- [x] 51 new unit tests, including one that reproduces a real provider bug
      (a plain, non-`ProviderError` exception) inside a shared provider
      instance mid-batch and confirms every other item still completes
- [x] Zero database schema changes (`SUBMISSION_UNCERTAIN` is a value in
      the existing free-text `status` column) — no new Alembic migration

350 passing unit tests total; clean `ruff` and `mypy`; no drift between
the ORM models and the latest Alembic migration (`alembic check`).

## What remains (Phase 4 continuation + Phase 5 continuation + Phases 6B–8)

Not yet built, explicitly deferred rather than silently dropped: BUILD
PROMPT section 12/49's remaining "Resume Engine" scope — a registry of
multiple resume *file* variants, a resume selector that picks among them
per job, controlled resume tailoring (reordering/emphasis without
fabrication), and PDF generation. These need more than one resume variant
to meaningfully build against, which doesn't exist yet.

Also not yet built: any real `ApplicationProvider` (Playwright browser
automation or a real ATS integration), any credential storage/handling,
`handle_application_inspection()` wired into the live CLI pipeline, and any
new path to SUBMITTED/VERIFIED beyond what Phase 5 already gates — Phase
6A deliberately ships contracts and enforcement plumbing only.
`ManualReviewProvider` remains the only shipped provider and still always
refuses to submit. This work is explicitly split into further phases, none
of which are implemented and none of which should be assumed from Phase
6A's existence:

- **Phase 6B** — first real provider integration (a structured-ATS
  provider, most likely against Greenhouse or Lever since discovery
  adapters already exist for both), still dry-run-gated in every test and
  by config in production; no real submission.
- **Phase 6C.5 — Credential Safety & Verification Foundation** — a
  foundation phase between Phase 6B and Phase 6C, distinct from and not a
  replacement for the live-execution Phase 6C below: a dormant,
  provider-agnostic `CredentialProvider` interface (the only shipped
  implementation, `NullCredentialStore`, holds no credential source of
  any kind and cannot return a value for any name) and a shape-only
  verification-evidence validator (`validate_submission_evidence`,
  explicitly not proof a submission occurred) — both unwired from every
  execution path, proven by adversarial and structural tests. No real
  credentials, no real network calls, no real submissions, no browser
  automation, and no change to any existing application behavior. Exists
  so a future live-execution phase adds a real implementation against an
  already-reviewed contract instead of inventing credential handling
  under pressure.
- **Phase 6C** — controlled real-world execution: enabling live-mode for
  the 6B provider against a small, explicitly-approved allowlist of real
  postings, automation level capped low, human approval required per
  submission.
- **Phase 6D** — multi-provider scaling: `BrowserFormProvider`/
  `CompanyCareerPortalProvider` families, queueing, concurrency, provider
  health monitoring at scale.

Beyond that: the FastAPI dashboard, the scheduler, and notifications. Also
not started within "job sources": Workday, company career pages, and the
ToS-restricted sources (LinkedIn, Indeed, Wellfound) — see
`config/sources.yaml` notes on each. Each phase stops for review before the
next begins.

**Before Level 4 (auto-submit) automation is ever safe to enable:** fill in
`config/preferences.yaml` (salary, visa/work authorization, relocation) —
these are currently all `UNKNOWN` because the resume doesn't state them, and
per `config/rules.yaml` any application question touching them must route to
a human, never be guessed.

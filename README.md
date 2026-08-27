# Career OS — Autonomous Global Job Discovery & Application Agent

A modular, auditable system that discovers job postings, matches them against
a truthful candidate knowledge base, and (in later phases) prepares and
submits applications — with humans in the loop by default and every
generated fact traceable to a source.

**This repository is at the end of Phase 4 (Resume Engine).** Resume
variant selection/tailoring, answer generation, and browser automation do
not exist yet. Nothing in this codebase can submit a job application.

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
  cli/                     Typer CLI (main.py)

prompts/                 Versioned prompt text (job_matcher.md)

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
insert-only, see above). The remaining tables (`resumes`, `applications`,
`application_answers`, `application_events`, `notifications`) are defined
now so schema and code evolve together, and get populated starting in
Phase 5.

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
`jobs match` still runs (deterministic-only) and says so explicitly.

Commands for later phases (`applications prepare/review/run`, `dashboard`)
are registered in the CLI now so the interface is stable, but exit with a
clear "not implemented yet" message — see `job_agent/cli/main.py`.

## Testing

```bash
pytest -q            # 165 tests: config, candidate schema/parser, db, job engine,
                      # matching engine, resume engine
ruff check src tests # lint — currently clean
mypy -p job_agent     # type check — currently clean
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

## What's implemented (Phase 1 + Phase 2 + Phase 3 + Phase 4)

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

165 passing unit tests total; clean `ruff` and `mypy`.

## What remains (Phase 4 continuation + Phases 5–8)

Not yet built, explicitly deferred rather than silently dropped: BUILD
PROMPT section 12/49's remaining "Resume Engine" scope — a registry of
multiple resume *file* variants, a resume selector that picks among them
per job, controlled resume tailoring (reordering/emphasis without
fabrication), and PDF generation. These need more than one resume variant
to meaningfully build against, which doesn't exist yet.

Beyond that: the answer-generation engine, Playwright browser automation,
the application state machine, the FastAPI dashboard, the scheduler,
notifications, and live-mode submission. Also not started within "job
sources": Workday, company career pages, and the ToS-restricted sources
(LinkedIn, Indeed, Wellfound) — see `config/sources.yaml` notes on each.
Each phase stops for review before the next begins.

**Before Level 4 (auto-submit) automation is ever safe to enable:** fill in
`config/preferences.yaml` (salary, visa/work authorization, relocation) —
these are currently all `UNKNOWN` because the resume doesn't state them, and
per `config/rules.yaml` any application question touching them must route to
a human, never be guessed.

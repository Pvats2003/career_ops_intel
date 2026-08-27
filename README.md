# Career OS — Autonomous Global Job Discovery & Application Agent

A modular, auditable system that discovers job postings, matches them against
a truthful candidate knowledge base, and (in later phases) prepares and
submits applications — with humans in the loop by default and every
generated fact traceable to a source.

**This repository is at the end of Phase 1 (Foundation).** Discovery,
matching, resume tailoring, and browser automation do not exist yet — see
[Roadmap](#roadmap). Nothing in this codebase can submit a job application.

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
  cli/                     Typer CLI (main.py)

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

## Database schema

SQLite via SQLAlchemy 2.0, migrated with Alembic. 15 tables (BUILD PROMPT
section 21's minimum set): `candidate`, `candidate_facts`, `skills`,
`experiences`, `projects`, `companies`, `job_sources`, `jobs`, `job_matches`,
`resumes`, `applications`, `application_answers`, `application_events`,
`notifications`, `system_events`.

Phase 1 only writes to `candidate`, `candidate_facts`, `skills`,
`experiences`, `projects` (via `job-agent profile parse`). The rest are
defined now so schema and code evolve together, and get populated starting
in Phase 2.

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
job-agent profile parse     # parse candidate/*.md + config/*.yaml, persist to DB
job-agent dry-run           # confirm submission is currently impossible
```

Commands for later phases (`jobs scan`, `jobs match`, `applications
prepare/review/run`, `dashboard`) are registered in the CLI now so the
interface is stable, but exit with a clear "not implemented yet" message —
see `job_agent/cli/main.py`.

## Testing

```bash
pytest -q            # 30 tests: config loader, candidate schema, parser, db repository
ruff check src tests # lint — currently clean
mypy -p job_agent     # type check — currently clean
```

Tests run against the **real** `candidate/*.md` and `config/*.yaml` files
(not synthetic fixtures), so they double as a regression check on the
shipped candidate data itself — e.g. `test_full_profile_assembly_never_
fabricates_preferences` asserts that salary/visa stay `UNKNOWN` because the
resume never states them.

## What's implemented (Phase 1)

- [x] Project structure, `pyproject.toml`, `.gitignore`, `.env.example`
- [x] Config system: 5 YAML files + strict Pydantic validation + env-var safety overrides
- [x] Candidate knowledge base authored from the real resume (no fabrication)
- [x] Canonical `CandidateProfile` schema with per-field provenance (`Fact[T]`, `SkillFact`)
- [x] Deterministic markdown parser (`job_agent.candidate.parser`), with clear errors on malformed input
- [x] Full 15-table database schema (SQLAlchemy 2.0) + Alembic migration
- [x] Candidate repository (idempotent upsert/reparse)
- [x] Structured JSON logging with secret redaction
- [x] CLI: `init`, `profile parse`, `status`, `health`, `dry-run` (+ stubs for later phases)
- [x] 30 passing unit tests; clean `ruff` and `mypy`

## What remains (Phases 2–8)

Not started: job source adapters (Greenhouse/Lever/Workday/etc.), job
normalization/deduplication/freshness, the matching engine, resume
selection/tailoring, the answer-generation engine, Playwright browser
automation, the application state machine, the FastAPI dashboard, the
scheduler, notifications, and live-mode submission. See the BUILD PROMPT's
Phase 2–8 breakdown for the full plan — each phase stops for review before
the next begins.

**Before Level 4 (auto-submit) automation is ever safe to enable:** fill in
`config/preferences.yaml` (salary, visa/work authorization, relocation) —
these are currently all `UNKNOWN` because the resume doesn't state them, and
per `config/rules.yaml` any application question touching them must route to
a human, never be guessed.

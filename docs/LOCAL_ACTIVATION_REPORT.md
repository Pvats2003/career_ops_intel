# Local activation report

An honest breakdown of what has actually been verified from inside this
development environment, versus what can only be confirmed on your own
machine, with your own credentials, or by your own decision. Categories
are kept separate deliberately — nothing here is upgraded to "verified"
just because it should probably work.

## VERIFIED IN SANDBOX

Actually run and checked, in this environment, this session:

- Full backend test suite: 1291 tests passed (0 failed), covering config
  loading, candidate parsing, matching, resume tailoring, cover letters,
  the application pipeline, the scheduler's due/skip logic, notifications,
  watchlists, career intelligence, URL validation/SSRF guards, and the
  web API.
- `job-agent doctor` runs end-to-end against the real repo and correctly
  reports PASS/WARN/ERROR/UNKNOWN per component (verified both against
  the real config and against synthetic test fixtures covering every
  status branch).
- `job-agent db upgrade` / `job-agent db current` run against the real
  database and correctly apply/report Alembic migrations.
- `job-agent init` scaffolds `.env` and runs the migration automatically.
- A real restart-persistence test: candidate/job/match/application rows
  written through one `Engine`, that `Engine` disposed (simulating a
  process exit), a brand-new `Engine` opened against the same database
  file, and every row read back correctly.
- The frontend build (`cd web-ui && npm run build`) succeeds and produces
  `web-ui/dist/`, which `job-agent serve` serves.
- `config/sources.yaml`: Remotive and Arbeitnow adapters are code-complete,
  tested, and enabled (keyless); Adzuna is enabled and correctly skips
  itself (logged, not an error) when credentials are absent; Greenhouse/
  Lever are correctly left disabled with placeholder tokens that `doctor`
  flags as an ERROR if you enable them without replacing.
- A real, previously-undiscovered defect: `alembic/env.py`'s
  `logging.config.fileConfig()` call was silently disabling every
  `job_agent` logger for the rest of the process on every Alembic
  invocation (a well-known Alembic gotcha). Fixed and covered by a
  regression test.
- A real, previously-undiscovered defect: `execute_search_run()` closed
  its HTTP client before the network scan that needed it ever ran,
  silently breaking every real search. Fixed and covered by a regression
  test (found in the prior activation-audit session).
- A real, previously-undiscovered defect: resume tailoring's skill-match
  checks used a stricter comparison than the scoring engine, so a skill
  like "Basic SQL" would score as a match but the tailored resume would
  claim "SQL not found in your profile". Fixed and covered by regression
  tests (found in the prior activation-audit session).
- **Postgres persistence (cloud-deployment readiness)**: a real local
  PostgreSQL 16 instance was started in this sandbox and all 12 existing
  Alembic migrations were applied to it from scratch with no errors;
  `job-agent doctor`, `job-agent health`, and `job-agent profile parse`
  all ran correctly against it, and credentials were confirmed redacted
  in every output. `DATABASE_URL` is the only thing that changes to move
  from SQLite to Postgres — no code path is SQLite-specific beyond
  `get_engine()`'s existing branch for it.
- `job-agent serve` now runs the Alembic upgrade automatically before it
  starts accepting requests (verified with a test that starts `serve`
  against a brand-new, never-migrated database and confirms it reaches
  head — necessary because a cloud platform's start command is the only
  thing that ever runs on a redeploy).
- The HTTP Basic Auth access gate (`APP_USERNAME`/`APP_PASSWORD`):
  verified it blocks every route (including the frontend shell) when
  configured, accepts only exact matching credentials, stays fully
  inactive when unset (local dev unchanged), and exempts `/api/health`
  specifically (confirmed a deployment platform's own health probe,
  which sends no credentials, would otherwise be locked out).
- `/api/health`'s enriched response (database connectivity, real
  migration-currency comparison against Alembic head, scheduler
  availability, per-source configuration status, LLM configuration) —
  verified it never contains a raw `database_url`, API key, or other
  credential even when one is set.
- The exact production start command, run directly (not inside Docker):
  `job-agent serve --host 0.0.0.0 --port $PORT` correctly bound the given
  port, served `/`, a client-side route (`/jobs`), a real 404 for an
  unknown `/api/*` path, and `/api/health`.
- The Anthropic API key was confirmed absent from the built frontend:
  grepped `web-ui/dist/` for both `ANTHROPIC` and `sk-ant` after a real
  `npm run build` — zero matches.
- A real gap found during the deployment security audit:
  `/api/candidate/resume` read an uploaded file into memory with no size
  limit — harmless when only reachable from localhost, genuinely
  exploitable once this dashboard has a public URL. Capped at 10MB with
  a regression test.

## REQUIRES MY MACHINE

Cannot be verified from this sandboxed development environment because
its network policy blocks all outbound HTTPS to job-source hosts
(confirmed via direct `curl` and the environment's own proxy status —
403 Forbidden on every one of remotive.com, arbeitnow.com, api.adzuna.com,
api.greenhouse.io, api.lever.co) — and, for the deployment work, blocks
pulling Docker base images from Docker Hub entirely (`docker build`
against this repo's `Dockerfile` failed with a 403 from the registry's
CDN; the proxy's own allowlist covers pypi/npm/crates/Go module proxies
but not container registries):

- Whether Remotive/Arbeitnow/Adzuna actually return real job listings —
  `job-agent doctor`/`/api/health` always report network as
  `UNKNOWN`/not-checked, never a fabricated `PASS`, for exactly this
  reason. Run `job-agent jobs search-run` once deployed to find out.
- Real end-to-end timing/performance of a live search (response times,
  parsing behavior against live API responses rather than fixtures).
- Whether your specific network (corporate proxy, firewall, VPN) needs
  any additional configuration to reach these APIs.
- **The actual `docker build .` of this repo's `Dockerfile`**, and
  therefore the deployed container's runtime behavior end to end. Every
  individual step the Dockerfile performs was verified by running it
  directly outside Docker (`pip install -e .`, `npm run build`,
  `job-agent serve --host 0.0.0.0 --port <PORT>`), but the image itself
  was never actually built or run in this sandbox. Render (and any other
  platform building from this same Dockerfile) builds it on its own
  infrastructure, which does not share this sandbox's network
  restriction — but this specific claim ("the Dockerfile builds cleanly
  end to end") is unverified by this session, not merely
  network-blocked-and-therefore-assumed-fine.
- Whether the actual Render deployment succeeds, since deploying requires
  a Render account, a payment method for the `starter` plan, and access
  to Render's own infrastructure — none of which this session has.

## REQUIRES MY CREDENTIALS

Cannot be enabled without a real credential only you can obtain:

- **Adzuna**: get a free `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` at
  https://developer.adzuna.com/ and put them in `.env`.
- **Anthropic (optional)**: get an `ANTHROPIC_API_KEY` at
  https://console.anthropic.com/ for LLM-refined matching/tailoring/chat.
  Everything works without it, deterministically.
- **Greenhouse/Lever (optional)**: if you want to track a specific
  company's board, you need that company's real board token/slug from
  their own careers page — these cannot be fabricated or guessed.

## REQUIRES MY DECISION

Fields the system will never guess on your behalf — it always shows
`UNKNOWN` (or `NOT CONFIGURED` in `job-agent doctor`'s output) until you
fill them in, in `config/preferences.yaml`:

- Remote/hybrid/onsite preference
- Willingness to relocate
- Notice period
- Target countries / open-to-countries
- Salary currency, minimum, target, negotiability
- Visa/sponsorship requirements per region (US/UK/EU/other) and
  nationality
- Earliest start date
- Whether to enable the autonomous scheduler's default 24h cadence or
  change `search_frequency_hours` from the Settings page
- Your own `APP_USERNAME`/`APP_PASSWORD` for the cloud deployment's access
  gate — see `docs/CLOUD_DEPLOYMENT.md`. Required before the deployed
  dashboard's URL is safe to open, let alone share.
- Whether to run the cloud deployment on Render's `starter` plan (real,
  always-on, persistent) or `free` (spins down when idle, database
  auto-expires) — `render.yaml` defaults to `starter` with the reasoning
  documented inline; only you can decide the tradeoff is worth ~$14/mo.

## NOT YET VERIFIED

Real, but only verifiable once the items above are resolved on your own
machine — listed here rather than silently assumed to work:

- Actual job-match quality against real (not fixture) job postings —
  whether the ranking correctly favors relevant, eligible, viable
  opportunities once real listings exist.
- Real LLM cost per search once `ANTHROPIC_API_KEY` is set and a live
  search runs (see `docs/cost_audit.md` for the logging mechanism, which
  is verified; the actual dollar numbers from a live run are not).
- Whether any specific company's Greenhouse/Lever board (once you add
  one) parses cleanly — the adapters are tested against synthetic
  fixtures, not that company's actual current API response shape.

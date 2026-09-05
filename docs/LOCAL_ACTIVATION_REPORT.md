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

## REQUIRES MY MACHINE

Cannot be verified from this sandboxed development environment because
its network policy blocks all outbound HTTPS to job-source hosts
(confirmed via direct `curl` and the environment's own proxy status —
403 Forbidden on every one of remotive.com, arbeitnow.com, api.adzuna.com,
api.greenhouse.io, api.lever.co):

- Whether Remotive/Arbeitnow/Adzuna actually return real job listings —
  `job-agent doctor` always reports network as `UNKNOWN`, never `PASS`,
  for exactly this reason. Run `job-agent jobs search-run` on your own
  machine to find out.
- Real end-to-end timing/performance of a live search (response times,
  parsing behavior against live API responses rather than fixtures).
- Whether your specific network (corporate proxy, firewall, VPN) needs
  any additional configuration to reach these APIs.

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

# Cloud deployment — Career OS at $0/month

**Committed architecture**: Render Free Web Service + Neon Free
PostgreSQL + this GitHub repository + an optional free UptimeRobot/
cron-job.org keep-alive. Browser-only access. No paid Render resources.
Mandatory hosting cost: **$0/month**.

Deploy the existing Career OS so it runs entirely in the cloud: open a
browser, go to one URL, log in, and everything — dashboard, job search,
matching, resume tailoring, cover letters, the application pipeline, the
autonomous scheduler — is already running. Nothing beyond a browser is
needed on the machine you use it from.

## $0 architecture (what actually runs where)

```
                    YOUR BROWSER
                         │
                         ▼
              https://career-os-xxxx.onrender.com
                         │
                    (HTTP Basic Auth:
                     APP_USERNAME/APP_PASSWORD)
                         │
                         ▼
        ┌────────────────────────────────────┐
        │   Render FREE Web Service           │
        │   (this repo's Dockerfile,          │
        │    one container, plan: free)        │
        │                                      │
        │   FastAPI (API + built frontend)     │
        │        +                             │
        │   APScheduler (in-process thread)    │
        └───────────────┬──────────────────────┘
                         │  DATABASE_URL
                         ▼
        ┌────────────────────────────────────┐
        │  Neon FREE PostgreSQL                │
        │  (external to Render — does NOT      │
        │   expire like Render's own free      │
        │   Postgres does)                     │
        │  candidate, jobs, matches,           │
        │  applications, search history        │
        └────────────────────────────────────┘
                         │
                         ▼
        Outbound HTTPS to job sources (Remotive,
        Arbeitnow, Adzuna) and, if configured,
        the Anthropic API — the key for which
        lives only on the server, never the browser.

        ┌────────────────────────────────────┐
        │  Optional: UptimeRobot/cron-job.org  │
        │  free monitor → GET /api/health      │
        │  every 5-10 min → keeps the free      │
        │  container from spinning down         │
        └────────────────────────────────────┘
```

Your office laptop needs only a browser and an internet connection —
nothing here runs on it.

## Before you start

- A GitHub account with this repository pushed to it.
- A Render account (no credit card needed for the free plan).
- A Neon account (no credit card needed for the free plan).

No paid account, credit card, or local install of Python/Node/Docker/Git
is required for any of this.

---

# $0 DEPLOYMENT — EXACT STEPS

### 1. Create a Neon account

Go to https://neon.tech and sign up free (GitHub sign-in is fastest).

### 2. Create a Neon project

From the Neon dashboard, click **Create a project**. Give it any name
(e.g. "career-os"). Neon creates the project and a default database in
one step.

### 3. Create the PostgreSQL database

Neon creates a default database for you as part of step 2 (usually named
`neondb`) — you don't need a separate step to create it unless you want a
differently-named one, in which case use Neon's **Databases** tab →
**New Database**.

### 4. Copy the connection string

Neon dashboard → your project → **Connection Details** (sometimes labeled
**Connection string**). Copy the string that starts with `postgresql://`
— it already includes `?sslmode=require`. Keep this tab open; you'll
paste it in step 10.

### 5. Open Render

Go to https://render.com and sign up free (GitHub sign-in is fastest).

### 6. Create a Blueprint

From the Render dashboard: **New +** → **Blueprint**.

### 7. Select the repository

Authorize Render to access your GitHub account if prompted, then select
this repository (`career_ops_intel`).

### 8. Select the correct branch

Render asks which branch to deploy. Choose your repository's default
branch (typically `main`) once this work is merged into it — or whichever
branch you intend to keep deploying from. This isn't hardcoded anywhere;
you choose it in this step, and Render remembers it for future
auto-deploys on push.

### 9. Select `render.free.yaml`

Render defaults to reading `render.yaml` (the paid recipe) from the repo
root. In the Blueprint creation screen, look for the blueprint file field
and change it to **`render.free.yaml`** instead — this is what makes the
web service use Render's free plan and skip creating a Render-managed
Postgres database.

### 10. Configure environment variables

Render shows the web service `render.free.yaml` defines
(`career-os`) with its declared environment variables. Fill in:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Paste the Neon connection string from step 4, exactly as copied |
| `APP_USERNAME` | Choose your own login username |
| `APP_PASSWORD` | Choose your own login password (not reused elsewhere) |
| `ANTHROPIC_API_KEY` | Optional — leave blank for deterministic-only matching/tailoring |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Optional — leave blank to skip the Adzuna source |

`DRY_RUN`, `LIVE_MODE`, `LOG_LEVEL`, `LOG_FORMAT`, `LLM_PROVIDER` are
already set to safe defaults by `render.free.yaml` — nothing to do there.

### 11. Deploy

Click **Apply** (or **Create Web Service**, depending on Render's current
UI wording). Render builds the Docker image and starts the container.

### 12. Wait for the build

Watch the **Logs** tab. A Docker build (Node stage + Python stage) takes a
few minutes on the free plan. A successful deploy ends with lines like:

```
Ensuring database schema is up to date...
Career OS dashboard starting at http://0.0.0.0:$PORT
Autonomous scheduled search enabled.
```

### 13. Open `/api/status`

Once the service shows "Live," open
`https://<your-service>.onrender.com/api/status` in a browser (this path
is behind your `APP_USERNAME`/`APP_PASSWORD` from step 10 — like every
route except `/api/health`, see "Keep-alive" below). You should see:

```json
{
  "status": "ok",
  "database": {"connected": true, "migrations_current": true},
  "scheduler": {"available": true},
  "job_sources": {"remotive": "enabled", "arbeitnow": "enabled", "adzuna": "enabled_no_credentials", "greenhouse": "disabled", "lever": "disabled"},
  "llm": {"configured": false}
}
```

`"connected": true` and `"migrations_current": true` confirm Neon is
really connected and the schema is current. If you instead see a
connection error here, double-check the `DATABASE_URL` you pasted in step
10 matches Neon's connection string exactly.

(`/api/health` itself returns only `{"status": "ok"}` — deliberately no
database round-trip, so Render's automated health check can never time
out just because Neon's free-tier compute is cold-starting. `/api/status`
is the endpoint that does the real diagnostics.)

### 14. Open Career OS

Visit `https://<your-service>.onrender.com` in a browser.

### 15. Log in

Your browser prompts for a username and password (native HTTP Basic Auth
— no custom login page). Enter the `APP_USERNAME`/`APP_PASSWORD` you set
in step 10. The browser remembers this for the session.

### 16. Configure preferences

On the dashboard, go to **Settings** and fill in your work/location/
salary/visa preferences (these start as `UNKNOWN` and are never guessed —
see `config/preferences.yaml`'s field list in `docs/ENVIRONMENT_VARIABLES.md`'s
companion doc, `docs/LOCAL_SETUP.md` step 8, for the full list).

### 17. Run your first real search

You don't have to do anything here — see "First real search" below for
why. If you want one immediately rather than waiting: open the
**Dashboard** and click **Run Search** (see `web-ui/src/pages/Dashboard.tsx`
and the `POST /api/jobs/search-run` endpoint it calls) — a real button in
the browser UI, no CLI or shell required.

### 18. Configure keep-alive (optional but recommended)

See "Keep-alive" below for exact setup. Recommended, not required — the
app works correctly either way, just with less predictable scheduler
timing without it.

---

## First real search

**No manual action is actually required.** `job-agent serve`'s scheduler
is configured to fire once immediately on process startup
(`next_run_time=datetime.now(UTC)` in `src/job_agent/jobs/scheduler.py`),
and since a brand-new deployment has no prior `SearchRun` row, the
due-check (`last_run is None`) evaluates to "due" on that very first tick.
In practice: your first real search runs automatically within moments of
the container starting in step 11/12, before you ever open the dashboard.

If you want to trigger another one on demand at any time — e.g. after
changing preferences — the **Run Search** button on the Dashboard page
calls `POST /api/jobs/search-run` directly from the browser. This is the
same code path the CLI's `job-agent jobs search-run` and the scheduler's
own tick both use; nothing about it is a lesser or fallback version.
Neither path requires Python, PowerShell, or Render's Shell tab (which
isn't available on the free plan in any case) on your office laptop.

## Scheduler safety

The scheduler runs in a background thread inside the same web service
process. What actually happens under each condition, verified by reading
`src/job_agent/jobs/scheduler.py` and `src/job_agent/jobs/search_run.py`:

- **Render sleeps** (free plan, ~15 min idle): the background thread
  simply isn't running while the container is stopped. Nothing breaks —
  when the container next wakes (an inbound request, or your keep-alive
  ping), the scheduler's next poll re-evaluates whether a search is due
  by comparing `search_frequency_hours` against the last **completed**
  run's real timestamp stored in the database, not against how long the
  process has been running. A search that was "due" while asleep runs as
  soon as the process wakes.
- **Render restarts or redeploys**: same reasoning — the due-check is
  entirely database-driven, so a fresh process picks up exactly where the
  data left off. No special handling was needed and none exists, because
  none is needed.
- **The process crashes mid-search**: a `SearchRun` row is written with
  `status="RUNNING"` before any real work starts, and only updated to
  `COMPLETED`/`PARTIAL`/`FAILED` at the end. A hard crash (not a caught
  exception) leaves that row stuck at `RUNNING` forever — but the
  due-check only ever looks at rows with `status IN (COMPLETED, PARTIAL)`,
  so a stuck `RUNNING` row is simply invisible to it. The next poll
  correctly treats a search as still due, exactly as if the crashed run
  had never started. Nothing gets permanently wedged.
- **Multiple instances accidentally start**: not a practical concern on
  this deployment — Render's free (and starter) web service plans run
  exactly one instance; there is no autoscaling to worry about here. (For
  completeness: if two instances ever did run concurrently, there is no
  distributed lock between them, so both could decide a search is due at
  the same moment and both would run one. This is a real, undocumented-
  elsewhere limitation of the current single-process design, not
  something this deployment's plan choice can trigger.)

**What this does NOT guarantee**: an exact time of day, or that a search
happens within any specific number of minutes of being "due." On the free
plan without a keep-alive, a search that becomes due while the container
is asleep runs whenever something next wakes it — which could be minutes
or, in the worst case, longer if nothing pings or visits it. It is never
skipped outright and never runs twice for the same due period; it can
only run late.

## Keep-alive

Recommended target: `GET /api/health`.

- **Fast, no I/O of any kind**: no config load, no database round-trip —
  a pure in-memory `{"status": "ok"}` response. It stays this way
  deliberately: Render's own automated health check hits this exact path,
  and if it did a database round-trip, a Neon free-tier cold-start
  reconnect delay could make the platform time it out and restart an
  otherwise-healthy instance. Verified by
  `test_health_endpoint_never_touches_config_or_database` in
  `tests/unit/test_web_api.py`.
- **No authentication required**: this path is explicitly exempted from
  the `APP_USERNAME`/`APP_PASSWORD` gate (see `_HEALTH_PATH` in
  `src/job_agent/web/app.py`) — a monitoring service can't authenticate,
  so gating it would make your own keep-alive lock itself out.
- **No secrets, no candidate data**: the response is always exactly
  `{"status": "ok"}` — never a database URL, API key, name, email, or any
  job/application content.
- Real diagnostics (database connectivity, migrations, job sources, LLM
  config) live at `/api/status` instead (see step 13 above) — that path
  does do a database round-trip, which is fine since nothing automated
  depends on it responding within a few seconds, only you, by hand, when
  troubleshooting. Verified by `tests/unit/test_health_status.py`.

**Setup**: sign up free at https://uptimerobot.com or https://cron-job.org,
add an HTTP(S) monitor for `https://<your-service>.onrender.com/api/health`,
interval 5 minutes (UptimeRobot's free-plan minimum; cron-job.org allows
similar). That single monitor both confirms the service is up and, as a
side effect, stops Render's free plan from ever fully spinning the
container down, since a spun-down container only wakes on an inbound
request — which this ping now supplies every 5 minutes.

**If the ping fails or lapses**: nothing breaks catastrophically. The
container spins down as it normally would on the free plan; the next
real visitor (you, opening the dashboard) or the next successful ping
wakes it back up, and the scheduler's database-driven due-check (see
"Scheduler safety" above) catches up correctly rather than skipping or
double-running. **A keep-alive does not guarantee zero downtime or exact
scheduler timing** — it only makes both closer to continuous than leaving
the free plan to spin down on its own.

## Database backup and restore (Neon, browser-only)

Because this is a $0 deployment, the simplest real backup strategy uses
Neon's own browser-based tools — no local `pg_dump`/`psql` install needed:

- **Branching (primary, recommended)**: Neon dashboard → your project →
  **Branches** → **Create branch**. This creates an instant, full,
  independent copy-on-write snapshot of your database at that moment —
  useful before any risky change (e.g. before testing a schema migration
  by hand, or before a bulk data cleanup). Restoring means pointing
  `DATABASE_URL` at the branch's own connection string (Render →
  Environment → `DATABASE_URL` → paste the branch's string → Save), or
  using Neon's **Restore** action to reset the main branch to an earlier
  point.
- **Point-in-time restore**: Neon's free tier retains a limited history
  window (this changes over time — check Neon's own pricing/limits page
  for the current retention period on the free plan) that lets you
  restore to any moment within that window directly from the dashboard,
  with no export/import step at all.
- **Optional: a real downloadable file backup**. If you specifically want
  an offline `.sql` file (e.g. to keep outside Neon entirely), that does
  require the standard Postgres client tools (`pg_dump`) on whatever
  machine runs the export — not your office laptop by design, but some
  machine with Python/a terminal. Command, run against the Neon
  connection string from step 4: `pg_dump "$DATABASE_URL" > backup.sql` to
  export, `psql "$DATABASE_URL" < backup.sql` to restore into a fresh
  database. This is optional and not required for the $0 architecture to
  be genuinely persistent — Neon's own branching already provides that
  without needing local tools.

## Free-tier resource limits (honest, not fabricated)

Free-tier limits on any platform change over time and this session
cannot browse Render's or Neon's current pricing pages to confirm exact
numbers as of when you read this — check their pricing pages directly
before relying on a specific figure. What's true by design, independent
of whatever the current numbers are:

- **Render Free**: the container spins down after a period of inbound-
  request inactivity and cold-starts on the next request; free plans
  have historically also carried a monthly usage-hour allowance shared
  across a Render account's free services. Neither 24/7 uptime nor an
  exact scheduler firing time is guaranteed on this plan (see "Scheduler
  safety" above).
- **Neon Free**: storage and monthly "compute" usage are capped (check
  Neon's current numbers); a personal single-candidate job-search
  database is small (candidate profile, jobs, matches, applications,
  search history — plain text and small numeric/JSON fields, no large
  binary blobs) and comfortably fits typical free-tier storage limits in
  practice, but this session cannot verify Neon's exact current cap.
- **UptimeRobot/cron-job.org free tiers**: typically cap the minimum
  monitor interval (commonly 5 minutes) and the number of free monitors —
  this deployment needs exactly one monitor, well within either service's
  free allowance historically, but again, verify current limits directly.
- **GitHub**: not used for any scheduled execution in this architecture
  (the scheduler runs inside the Render container, not as a GitHub
  Actions workflow) — no GitHub Actions minutes are consumed by this
  deployment at all.

This is not a promise of unlimited storage, unlimited job searches, or
guaranteed 24/7 uptime — it's an honest $0 system with the tradeoffs
above, not a disguised paid system.

---

## Environment variables — exact minimal set

```text
DATABASE_URL=
APP_USERNAME=
APP_PASSWORD=
```

Optional (every one has a working fallback when left blank):

```text
ANTHROPIC_API_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
```

Full details (purpose, where each goes, where to obtain it, whether it's
a secret) are in `docs/ENVIRONMENT_VARIABLES.md`. Never put real values
in the repository — both `render.yaml` and `render.free.yaml` mark every
secret `sync: false`, meaning Render always asks you to fill it in by
hand rather than reading a committed value.

## What you'll do daily

Open the URL, log in once per browser session if prompted, and use the
dashboard exactly as documented in `docs/LOCAL_SETUP.md` steps 13-15 —
review new opportunities, open a job, tailor your resume, generate a
cover letter, work the Application Assistant, and move things through
your pipeline. The scheduler has already done the discovery work before
you open the tab.

## Security notes specific to this deployment

- `ANTHROPIC_API_KEY` and `DATABASE_URL` exist only as server-side
  environment variables on Render; they are never sent to the browser or
  embedded in the frontend bundle (verified: neither string appears
  anywhere in `web-ui/dist/` after a build).
- CORS is not an issue in this deployment: the frontend and API are
  served from the same origin (one Render URL), so the browser never
  makes a cross-origin request to begin with.
- The access gate (`APP_USERNAME`/`APP_PASSWORD`) covers every route,
  including the frontend shell itself, except `/api/health` — verified by
  `tests/unit/test_web_auth_gate.py`, including that neither a failed nor
  a successful login attempt ever writes the real password (or a raw
  Authorization header) into application logs.
- SSRF protections on generated/redirect-followed application URLs
  (`job_agent/jobs/url_check.py`) and the resume-upload size cap
  (`job_agent/web/routers/candidate.py`) are unchanged by deployment —
  they apply identically in the cloud.
- `DRY_RUN=true`/`LIVE_MODE=false` ship as the default in both
  `render.yaml` files: no application can be auto-submitted regardless of
  where this runs.
- Neon's connection string always includes `?sslmode=require` — the
  connection to your database is encrypted in transit; nothing in this
  codebase strips or overrides that.

## If something doesn't work

Is this a code problem (check Render's **Logs** tab for a traceback), a
missing/wrong credential (check `/api/status` and the Environment tab —
`"connected": false` almost always means `DATABASE_URL` doesn't match
what Neon gave you), or a plan limitation (free-tier spin-down, most
commonly, showing up as a slow first request after idle time)?
`job-agent doctor` isn't reachable remotely, but the same underlying
checks are what `/api/status` reports (`/api/health` itself only ever
reports process liveness, not database/scheduler/source status).

## Optional: upgrading later to the paid, always-on recipe

If you later decide the $0 tradeoffs aren't worth it, `render.yaml` (the
paid recipe, ~$14/mo total) is still in this repository and gets you an
always-on container with a database that never expires, no keep-alive
needed. Nothing about the $0 deployment locks you out of switching —
export your Neon data (see "Database backup and restore" above) and
follow `render.yaml`'s setup instead. This isn't required, and the $0
recipe above is the currently committed architecture.

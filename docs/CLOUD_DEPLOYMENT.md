# Cloud deployment — Career OS on Render

Deploy the existing Career OS so it runs entirely in the cloud: open a
browser, go to one URL, and everything — dashboard, job search, matching,
resume tailoring, cover letters, the application pipeline, the autonomous
scheduler — is already running. No Python, Node, or terminal on the
machine you use it from.

This guide targets **Render** (render.com). Why Render and not Railway,
Fly.io, or something else: Career OS is a single FastAPI process that
already serves the built frontend and runs its own scheduler in a
background thread (see `src/job_agent/jobs/scheduler.py`) — there is no
separate frontend host, no separate worker process, and no complex
multi-service topology to configure. Render's "one web service + one
managed database" model is the simplest fit for exactly that shape, its
free tier is enough to evaluate the whole flow before paying anything, and
connecting a GitHub repo through its dashboard requires no CLI tooling on
your machine. Railway and Fly.io could run the same Dockerfile with
similar steps if you already prefer one of them.

## Architecture (what actually runs where)

```
                    YOUR BROWSER
                         │
                         ▼
              https://career-os-xxxx.onrender.com
                         │
                         ▼
        ┌────────────────────────────────────┐
        │   Render Web Service (this repo's   │
        │   Dockerfile, one container)        │
        │                                      │
        │   FastAPI (API + built frontend)     │
        │        +                             │
        │   APScheduler (in-process thread)    │
        │   -- daily job search, no browser    │
        │      or separate process needed      │
        └───────────────┬──────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  Render managed PostgreSQL          │
        │  (candidate, jobs, matches,         │
        │   applications, search history)     │
        └────────────────────────────────────┘
                         │
                         ▼
        Outbound HTTPS to job sources (Remotive,
        Arbeitnow, Adzuna) and, if configured,
        the Anthropic API — the key for which
        lives only on the server, never the browser.
```

Nothing here requires your office laptop to run anything except the
browser tab. The scheduler keeps searching daily whether or not that tab
is open.

## Before you start

- A GitHub account with this repository pushed to it (fork it if it's not
  already yours).
- A credit card, even to use Render's free tier for evaluation — real,
  unattended daily operation needs the paid `starter` plan (~$7/mo per
  service, ~$14/mo total for the web service + database). See the plan
  note in `render.yaml` and step 9 below for why free-tier is not
  sufficient for "runs even when my browser is closed."

## Steps

### 1. Create a Render account

Go to https://render.com and sign up (GitHub sign-in is the fastest path
and doubles as step 2).

### 2. Connect your GitHub repository

From the Render dashboard: **New +** → **Blueprint**. Authorize Render to
access your GitHub account if prompted, then select this repository.

### 3. Choose the deployment service

Render reads `render.yaml` from the repo root automatically and shows you
a preview: one **Web Service** (`career-os`, built from this repo's
`Dockerfile`) and one **PostgreSQL** database (`career-os-db`). Click
**Apply** to create both. This one file is doing the work of "configure
backend," "configure frontend," and "configure database" below — they're
already wired together in `render.yaml`, described here so you understand
what got created.

### 4. Backend configuration (already done by render.yaml)

The web service builds this repo's `Dockerfile`, which installs the
backend (`pip install -e .`) and runs `job-agent serve --host 0.0.0.0
--port $PORT` as its start command. `$PORT` is injected by Render — you
don't set it. Nothing to do here beyond confirming the service shows
"Live" after step 9.

### 5. Frontend configuration (already done by render.yaml)

The same `Dockerfile` builds the React frontend (`npm run build`) in its
first stage and copies the result into the image; the one FastAPI process
serves it from the same origin as the API, so there's no separate frontend
host, no CORS configuration, and no second URL to remember.

### 6. Database configuration (already done by render.yaml)

Render provisions the `career-os-db` Postgres instance and injects its
connection string into the web service as `DATABASE_URL` automatically
(see the `fromDatabase` entry in `render.yaml`) — you never type a
database URL or password by hand. This is real persistence: the database
is a separate managed resource from the web service's container, so
redeploying, restarting, or even deleting and recreating the web service
does not touch its data.

### 7. Scheduler configuration (already done — no separate service)

The autonomous scheduler runs inside the same web service process (see
the architecture diagram above) and is on by default (`job-agent serve`'s
`--scheduler` flag, default enabled). It searches once per
`search_frequency_hours` (default 24h, changeable from the dashboard's
Settings page once you're logged in) — no cron job, no second Render
service, and no open browser tab required.

### 8. Add environment variables

In the Render dashboard, open the `career-os` web service → **Environment**.
`render.yaml` already declared these; fill in real values:

| Variable | Required? | What it does |
|---|---|---|
| `APP_USERNAME` / `APP_PASSWORD` | **Yes, before you tell anyone the URL** | Gates the entire dashboard behind HTTP Basic Auth. This is a personal dashboard with your name, resume, and salary expectations on it — without these set, anyone who finds the URL can open it. |
| `ANTHROPIC_API_KEY` | Optional | Enables LLM-refined matching/tailoring/cover letters/career chat. Get one at https://console.anthropic.com/. Everything works without it, deterministically. |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Optional | Enables the Adzuna job source. Free at https://developer.adzuna.com/. Remotive and Arbeitnow need no credentials and work without these. |

`DATABASE_URL`, `DRY_RUN`, `LIVE_MODE`, `LOG_LEVEL`, `LOG_FORMAT` are
already set by `render.yaml` — leave them as-is unless you specifically
mean to change them (see README.md's safety-rules section before ever
touching `DRY_RUN`/`LIVE_MODE`).

Click **Save Changes** — Render redeploys automatically when you do.

### 9. Deploy

If you haven't already saved environment variables (which triggers a
redeploy), click **Manual Deploy** → **Deploy latest commit** on the
`career-os` service. Watch the **Logs** tab; a successful deploy ends with
lines like:

```
Ensuring database schema is up to date...
Career OS dashboard starting at http://0.0.0.0:$PORT
Autonomous scheduled search enabled.
```

**Before relying on this for daily use**, switch both the web service and
the database from Render's `free` plan to `starter` (Settings → Instance
Type, for each resource) if you started on free. Render's free web
service plan spins the container down after ~15 minutes with no incoming
request — which also stops the in-process scheduler thread — and free
Postgres instances auto-expire and get deleted after a fixed number of
days. Neither of those is compatible with "keeps searching daily whether
or not I've opened the dashboard," which is the whole point of this
deployment.

### 10. Verify health

Once the service shows "Live," open `https://<your-service>.onrender.com/api/health`
in a browser (this one endpoint is never gated by `APP_USERNAME`/
`APP_PASSWORD` — a deployment platform's own health probe can't
authenticate, so it has to stay open, and it never returns a credential or
connection string). You should see something like:

```json
{
  "status": "ok",
  "database": {"connected": true, "migrations_current": true},
  "scheduler": {"available": true},
  "job_sources": {"remotive": "enabled", "arbeitnow": "enabled", "adzuna": "enabled_no_credentials", "greenhouse": "disabled", "lever": "disabled"},
  "llm": {"configured": false}
}
```

`"connected": true` and `"migrations_current": true` confirm the database
is real and current. `"llm": {"configured": false}` just means you haven't
set `ANTHROPIC_API_KEY` — not an error.

### 11. Open the dashboard

Visit `https://<your-service>.onrender.com` in a browser. If you set
`APP_USERNAME`/`APP_PASSWORD`, the browser will prompt for them once
(Basic Auth) — enter them and the browser remembers for the session.
You should land on the Career OS dashboard.

### 12. Run your first real search

From the dashboard, trigger a search the same way you would locally, or
wait for the scheduler's next cycle. To run one immediately without
waiting: Render's dashboard → your service → **Shell** tab gives you a
one-off terminal inside the running container, where you can run:

```
job-agent jobs search-run
```

From then on, the scheduler keeps this current automatically — no manual
step needed for subsequent searches.

## Credentials checklist

- [ ] `APP_USERNAME` / `APP_PASSWORD` — required before sharing the URL with anyone, including yourself on another device.
- [ ] `ANTHROPIC_API_KEY` — optional, from https://console.anthropic.com/.
- [ ] `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` — optional, free, from https://developer.adzuna.com/.

Nothing else needs a credential you supply — `DATABASE_URL` is generated
and injected by Render itself.

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
  including the frontend shell itself, except `/api/health`.
- SSRF protections on generated/redirect-followed application URLs
  (`job_agent/jobs/url_check.py`) and the resume-upload size cap
  (`job_agent/web/routers/candidate.py`) are unchanged by deployment —
  they apply identically in the cloud.
- `DRY_RUN=true`/`LIVE_MODE=false` ship as the default in `render.yaml`:
  no application can be auto-submitted regardless of where this runs.

## If something doesn't work

Run through `docs/LOCAL_ACTIVATION_REPORT.md`'s categories mentally: is
this a code problem (check Render's Logs tab for a traceback), a missing
credential (check `/api/health` and the Environment tab), or a plan
limitation (free-tier spin-down, most commonly)? `job-agent doctor` isn't
reachable remotely, but the same underlying checks are what `/api/health`
reports.

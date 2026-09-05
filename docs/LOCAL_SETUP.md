# Local setup — Career OS on your own machine

Exact commands, in order, to get Career OS running on a normal Windows
machine (or Linux/Mac — noted where different). Run `job-agent doctor` at
any point if something doesn't look right; it tells you exactly what's
missing and how to fix it.

## 0. Prerequisites

Install these first if you don't already have them:

- **Git**: https://git-scm.com/downloads
- **Python 3.11 or newer**: https://www.python.org/downloads/ — on the
  Windows installer, check **"Add python.exe to PATH"**.
- **Node.js 20 or newer** (only needed to build the web dashboard):
  https://nodejs.org/

Verify each installed correctly:

```powershell
git --version
python --version
node --version
npm --version
```

## 1. Clone the repository

```powershell
git clone <your-fork-or-repo-url> career_ops_intel
cd career_ops_intel
```

(If you already have the repository open in an editor/IDE, just open a
terminal in its root folder instead.)

## 2. Create and activate the Python environment

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script, run this once (in an
admin PowerShell) and try again: `Set-ExecutionPolicy -Scope CurrentUser
RemoteSigned`.

Linux/Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now start with `(.venv)`. Every command below assumes
this environment is active.

## 3. Install backend dependencies

```powershell
pip install -e ".[dev]"
```

This installs the `job-agent` command itself plus everything it needs
(FastAPI, SQLAlchemy, Alembic, Anthropic SDK, Playwright, pytest, etc.).

## 4. Install frontend dependencies

```powershell
cd web-ui
npm install
cd ..
```

## 5. Create your `.env`

```powershell
job-agent init
```

This copies `.env.example` to `.env` (only if `.env` doesn't already
exist), creates the `data/` directory, and brings the database schema up to
date. It never overwrites an existing `.env` or existing config/candidate
files.

Now open `.env` in a text editor and fill in the secrets you want to use —
see `.env.example` for what each variable is, whether it's required, and
where to get it. At minimum, decide now whether you're setting
`ANTHROPIC_API_KEY` and/or `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` (both optional
— see steps 8-9).

## 6. Configure job sources

Open `config/sources.yaml`. Out of the box:

- **Remotive** and **Arbeitnow** are already `enabled: true` and need no
  credentials — they'll start returning real jobs the moment you run a
  search from a machine with normal internet access.
- **Adzuna** is `enabled: true` but skipped until you set
  `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` in `.env`. Get free credentials at
  https://developer.adzuna.com/, paste them into `.env`, and it activates
  automatically — no code or config change needed.
- **Greenhouse**/**Lever** are `enabled: false` with placeholder board
  tokens. To track a specific company that uses Greenhouse or Lever, find
  their board token/slug on their own careers page URL (e.g.
  `boards.greenhouse.io/<token>` or `jobs.lever.co/<slug>`), replace the
  `REPLACE_WITH_...` placeholders under that source's `boards:` list with
  real values, and set `enabled: true`.

You don't have to touch this file to get your first real search — Remotive
and Arbeitnow work immediately.

## 7. Configure Anthropic (optional)

Setting `ANTHROPIC_API_KEY` in `.env` enables LLM-refined match summaries,
resume-tailoring prose, and the career chat assistant. Get a key at
https://console.anthropic.com/. Leaving it blank is fully supported —
matching, resume tailoring, and cover letters all still work, just with
deterministic (non-LLM) text instead of LLM-refined prose.

## 8. Configure candidate preferences

Open `config/preferences.yaml`. Every field starts as the literal string
`"UNKNOWN"` until you fill it in — the system never guesses these. Fill in
at least:

- `work_preferences.remote` (`remote` / `hybrid` / `onsite`)
- `work_preferences.willing_to_relocate` (`true` / `false`)
- `work_preferences.notice_period`
- `location_preferences.open_to_countries`
- `salary_preferences.*` (currency, minimum, target, negotiable)
- `visa_information.*` (nationality, sponsorship requirements per region)
- `availability.earliest_start_date`

Run `job-agent doctor` after editing — it lists every field still marked
`NOT CONFIGURED` in `config/preferences.yaml` by exact path, so you know
you've covered everything.

Your résumé/experience/skills/projects/education live under `candidate/`
(Markdown files) — edit those directly if anything needs updating; run
`job-agent profile parse` afterward to re-parse and re-validate them.

## 9. Initialize the database

Already done by `job-agent init` in step 5. To re-run it explicitly later
(e.g. after `git pull` adds a new file under `alembic/versions/`):

```powershell
job-agent db upgrade
job-agent db current    # shows the current schema revision
```

Both are safe to run any time, including when already up to date.

## 10. Build the frontend

```powershell
cd web-ui
npm run build
cd ..
```

This writes `web-ui/dist/`, which `job-agent serve` serves automatically.
Re-run this after pulling frontend changes. (For active frontend
development, run `npm run dev` inside `web-ui/` instead — see step 12.)

## 11. Start everything (backend + frontend + scheduler)

```powershell
job-agent serve
```

This one command starts the FastAPI backend, serves the built dashboard,
and starts the autonomous scheduler (default: one real search per 24h,
configurable from the Settings page). It listens on
http://127.0.0.1:8000 by default. Stop it with Ctrl+C.

To disable the autonomous scheduler (e.g. while testing): `job-agent serve
--no-scheduler`. To change the port: `job-agent serve --port 8080`.

## 12. (Optional) Frontend development mode

If you're actively editing the frontend, run the backend (as in step 11)
and the Vite dev server separately so changes hot-reload:

```powershell
job-agent serve
```

```powershell
cd web-ui
npm run dev
```

`npm run dev` proxies API calls to the backend, so use the URL it prints
(typically http://localhost:5173) instead of the backend's own port while
developing.

## 13. Check health

```powershell
job-agent doctor
```

Or, while `job-agent serve` is running, open http://127.0.0.1:8000/api/health
in a browser, or:

```powershell
curl http://127.0.0.1:8000/api/health
```

`job-agent doctor` never reports network reachability as PASS — it makes
no outbound calls itself. The real test of connectivity is step 14.

## 14. Run your first real search

With `job-agent serve` running in one terminal, run this in another
(same virtual environment activated):

```powershell
job-agent jobs search-run
```

This generates a search-query portfolio from your candidate profile, scans
every enabled source, marks stale jobs expired, scores and ranks every job
against your profile, and records a `SearchRun` row. It prints a summary of
what happened. If every source is unreachable (e.g. corporate firewall,
proxy, or offline), it reports that honestly — it never fabricates
results.

## 15. Open the dashboard

Open http://127.0.0.1:8000 in a browser. You should see the day's Top
opportunities, application pipeline, and career intelligence built from
the search you just ran.

---

See also:

- `docs/FIRST_RUN_CHECKLIST.md` — the shortest possible path through the
  above, as a plain numbered checklist.
- `docs/LOCAL_ACTIVATION_REPORT.md` — what's been verified from inside the
  sandboxed development environment vs. what only your own machine,
  credentials, or decisions can confirm.
- `.env.example` — every environment variable, its purpose, whether it's
  required, and where to obtain it.

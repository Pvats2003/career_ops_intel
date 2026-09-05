# First-run checklist

The shortest path from a fresh checkout to your first real job search.
Full detail on each step lives in `docs/LOCAL_SETUP.md` — this page is
just the order to do things in.

**STEP 1**
Install prerequisites: Git, Python 3.11+, Node.js 20+.

**STEP 2**
Open a terminal in the repository folder.

**STEP 3**
Create and activate the Python environment:
`python -m venv .venv` then activate it
(`.venv\Scripts\Activate.ps1` on Windows, `source .venv/bin/activate` on
Linux/Mac).

**STEP 4**
Install dependencies:
`pip install -e ".[dev]"` then `cd web-ui && npm install && cd ..`

**STEP 5**
Run:
`job-agent init`
This creates `.env` from `.env.example` and sets up the database.

**STEP 6**
Open `.env`. Decide whether to add `ANTHROPIC_API_KEY` (optional — enables
LLM features) and/or `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` (optional — enables
the Adzuna job source). Both can stay blank; Remotive and Arbeitnow work
without any credentials.

**STEP 7**
Open `config/preferences.yaml`. Fill in every field still marked
`"UNKNOWN"` — remote preference, relocation, notice period, salary,
visa/sponsorship, target countries, earliest start date. Never leave these
for the system to guess.

**STEP 8**
Build the frontend:
`cd web-ui && npm run build && cd ..`

**STEP 9**
Run:
`job-agent doctor`

**STEP 10**
Fix anything marked `[ERROR]`. Review anything marked `[WARN]` — most are
fine to proceed with (e.g. "Anthropic not configured" just means no LLM
features yet), but don't ignore one you don't understand.

**STEP 11**
Start Career OS:
`job-agent serve`
Leave this running in its own terminal.

**STEP 12**
In a second terminal (same virtual environment activated), run:
`job-agent jobs search-run`

**STEP 13**
Open the dashboard: http://127.0.0.1:8000

**STEP 14**
Review the Top opportunities list. Open one that looks strong — check its
match score, application viability, and application URL.

**STEP 15**
Choose your first application from the Job Detail page: use "Why I Match",
tailor your resume, generate a cover letter, and go through the
Application Assistant. Nothing submits automatically — you always take the
final "apply" action yourself.

That's the whole loop. From here, `job-agent serve` keeps running (with its
built-in scheduler doing a fresh search every 24h by default), and you come
back to the dashboard whenever you want to review new opportunities.

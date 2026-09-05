# Environment variables — master list

Every environment variable the application actually reads, sourced
directly from `job_agent.config.loader.EnvSettings` (the single place
they're all defined — nothing here is speculative). Local dev reads these
from `.env` (via `job-agent init`, which copies `.env.example`); a cloud
deployment sets them in the platform's Environment settings instead.

| Variable | Required? | Where it goes | Where to obtain it | Example | Secret? |
|---|---|---|---|---|---|
| `DATABASE_URL` | **Required for deployment** | Render/host environment variable | Render: auto-injected from its managed Postgres. Neon (the $0 recipe): Neon dashboard → your project → Connection Details → copy the connection string | `postgresql://user:pw@ep-xxx.neon.tech/neondb?sslmode=require` | Yes |
| `APP_USERNAME` | **Required before the URL is public** | Render/host environment variable | You choose it | `candidate` | No (but pair with a real password) |
| `APP_PASSWORD` | **Required before the URL is public** | Render/host environment variable | You choose it | a real passphrase, not reused elsewhere | `sk9x-quartz-heron-42` | Yes |
| `ANTHROPIC_API_KEY` | Optional | Render/host environment variable | https://console.anthropic.com/ → Settings → API Keys | `sk-ant-api03-...` | Yes |
| `LLM_PROVIDER` | Optional | Render/host environment variable (defaults to `anthropic` in both render.yaml files) | You set it; `anthropic` is the only supported value today | `anthropic` | No |
| `LLM_MODEL` | Optional | Render/host environment variable | Leave unset to use the provider's own default model | (leave blank) | No |
| `ADZUNA_APP_ID` | Optional | Render/host environment variable | https://developer.adzuna.com/ → register → create an App | `a1b2c3d4` | Yes |
| `ADZUNA_APP_KEY` | Optional | Render/host environment variable | Same Adzuna App page as above | `e5f6a7b8c9d0...` | Yes |
| `DRY_RUN` | Optional (both render.yaml files set it) | Render/host environment variable | Safety switch — leave `true` unless you've read README.md's safety-rules sections and mean to change it | `true` | No |
| `LIVE_MODE` | Optional (both render.yaml files set it) | Render/host environment variable | Safety switch — leave `false` unless you mean it | `false` | No |
| `LOG_LEVEL` | Not required (has a sensible default) | Render/host environment variable | `DEBUG`\|`INFO`\|`WARNING`\|`ERROR` | `INFO` | No |
| `LOG_FORMAT` | Not required (has a sensible default) | Render/host environment variable | `json`\|`text` | `json` | No |
| `CONFIG_DIR` | Not required (correct default for a normal checkout) | Local `.env` only — never needed in the cloud deployment, since the Dockerfile always puts `config/` at the expected path | n/a | `config` | No |
| `CANDIDATE_DIR` | Not required (correct default for a normal checkout) | Local `.env` only — same reasoning as `CONFIG_DIR` | n/a | `candidate` | No |

## REQUIRED FOR DEPLOYMENT

```text
DATABASE_URL=
APP_USERNAME=
APP_PASSWORD=
```

Without these three, the app either has nowhere persistent to store data
(`DATABASE_URL`) or is reachable by anyone who finds the URL
(`APP_USERNAME`/`APP_PASSWORD`).

## OPTIONAL

```text
ANTHROPIC_API_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
```

Every one of these has a fully working fallback when left blank:
deterministic (non-LLM) matching/tailoring/cover letters without
`ANTHROPIC_API_KEY`; the Adzuna source cleanly skips itself (logged, never
an error) without both Adzuna variables. `LLM_PROVIDER`/`LLM_MODEL` are
also optional but already set to sensible values in both `render.yaml`
files — you only touch them if you specifically want to change the model.

## NOT REQUIRED

`DRY_RUN`, `LIVE_MODE`, `LOG_LEVEL`, `LOG_FORMAT` all ship with safe
defaults and are already set explicitly in both `render.yaml`/
`render.free.yaml` files — you don't need to touch them for a working
deployment. `CONFIG_DIR`/`CANDIDATE_DIR` are local-development-only paths
that the Docker image's own directory layout makes irrelevant in the
cloud; never set these on Render.

## Where to paste `DATABASE_URL` for the $0 (Neon) deployment

1. Neon dashboard → your project → **Connection Details**.
2. Copy the string that starts with `postgresql://` (it already includes
   `?sslmode=require` — paste it exactly, don't edit it).
3. Render dashboard → your `career-os` service → **Environment** →
   `DATABASE_URL` → paste it in → **Save Changes**.

The application accepts this string exactly as Neon gives it — no manual
edits needed. (Internally, `job_agent.db.session.normalize_database_url()`
rewrites the driver portion of the URL to the one actually installed;
you never have to do this by hand.)

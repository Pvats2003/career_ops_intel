# InstaCore Sync

**InstaCore Sync** is a production-grade Windows desktop application that fully
automates a repetitive daily workflow: ~150–200 Instacore screen-recording
videos arrive on WhatsApp Desktop every day, each showing an Android device
running the Instacore app with a **Device ID** (`IC-188`, `IC-551`, `IC-23`, ...)
visible near the top of the screen in the first few seconds.

Instead of manually downloading, watching, sorting, uploading, and
link-pasting each video, InstaCore Sync watches the WhatsApp download folder,
reads the Device ID with OCR, uploads the video to the correct dated/IC
folder in Google Drive, writes the shareable link into Google Sheets, and
files the video away — automatically, continuously, with retries, dedup,
and a live dashboard.

```
WhatsApp folder  →  Folder Watcher  →  OCR (Device ID)  →  Google Drive  →  Google Sheets  →  Processed/
                                            │
                                    low confidence
                                            ▼
                                     Needs Review/
```

## Highlights

- **Zero-touch ingestion** — a `watchdog`-based folder watcher plus a
  periodic reconciliation pass means no video is ever missed, even across
  app restarts or dropped filesystem events.
- **Bounded, concurrent, resumable uploads** — an asyncio worker pool
  drives 10–20 simultaneous Google Drive uploads with exponential-backoff
  retries, without blocking the UI.
- **Multi-engine OCR** — Tesseract (fast, default) and PaddleOCR (heavier,
  often more accurate), switchable per-user, with an "Auto" mode that runs
  both and keeps the highest-confidence match. Frame sampling is bounded to
  the first few seconds unless a full-video fallback scan is needed.
- **SHA-256 deduplication** — every video is hashed before upload; a video
  already uploaded (even under a different filename) is skipped, not
  re-uploaded.
- **Never blocks on a bad video** — OCR failures route to a `Needs Review`
  folder; upload failures retry, then route to `Failed`; the pipeline keeps
  processing everything else regardless.
- **Needs Review screen** — for the videos OCR genuinely can't read, a
  thumbnail, the raw OCR text, and its confidence, with a manual Device ID
  entry that routes straight to upload (skipping a redundant OCR re-run).
- **Pause/resume + one-click retry** — stop new uploads from starting
  without losing what's already queued, and re-queue a specific failed
  video from the Queue view.
- **Encrypted credentials at rest** — the Google OAuth token is protected
  with Windows DPAPI (Fernet fallback elsewhere), never written to disk in
  plaintext; see `docs/SECURITY.md`.
- **Modern, dark, glass-panel desktop UI** built with PySide6 — live
  dashboard (queue depth, transfer speed, ETA, OCR confidence), a
  searchable/filterable/CSV-exportable log with per-stage timing (OCR/
  upload/total), desktop notifications, and a full Settings screen with
  config export/import.
- **SQLite-backed** job tracking and a durable audit log, with WAL mode so
  the UI never blocks on writer threads, and automatic pruning of old
  completed entries so the working table doesn't grow forever.
- Clean, feature-based, dependency-injected architecture with type hints
  throughout and a real unit + integration test suite (141 tests,
  including a concurrency stress test that drives dozens of videos through
  the real async worker pool under induced random failures).

## Project layout

```
whatsapp_video_automation/
├── src/instacore_sync/
│   ├── core/            settings (pydantic), DI container, logging, exceptions
│   ├── domain/           Pydantic models + enums shared across layers
│   ├── db/                SQLite connection mgmt, migrations, repositories
│   ├── services/
│   │   ├── watcher/        WhatsApp folder watcher (watchdog + stability check)
│   │   ├── video/           bounded frame sampling (OpenCV)
│   │   ├── ocr/               Tesseract / PaddleOCR engines + Device ID extraction
│   │   ├── hashing/            SHA-256 streaming hash
│   │   ├── dedup/                duplicate-upload prevention
│   │   ├── drive/                  Google Drive OAuth, folders, resumable upload
│   │   ├── sheets/                  Google Sheets row find/update
│   │   ├── upload/                    asyncio bounded-concurrency worker pool
│   │   └── pipeline/                    orchestrator wiring everything together
│   ├── workers/           Qt/asyncio bridge (dedicated pipeline thread)
│   └── ui/                 PySide6 dashboard, queue, logs, settings, dark/light theme
├── tests/                 unit + integration tests (pytest)
├── packaging/              PyInstaller spec, Inno Setup installer script, build.bat
├── scripts/                 standalone DB init/inspection CLI
├── config/                  settings.example.yaml (copy → settings.local.yaml)
└── docs/                    setup guides, architecture, DB schema
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how the pieces fit
together, [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) for the SQLite
schema, [`docs/SETUP.md`](docs/SETUP.md) to run it locally,
[`docs/GOOGLE_API_SETUP.md`](docs/GOOGLE_API_SETUP.md) to wire up Drive/Sheets
access, [`docs/PACKAGING.md`](docs/PACKAGING.md) to build the Windows
installer, [`docs/SECURITY.md`](docs/SECURITY.md) for the credential/security
model, and — if you're rolling this out to a team rather than running it
yourself — [`docs/DEPLOYMENT_AT_SCALE.md`](docs/DEPLOYMENT_AT_SCALE.md) for
what changes (and what you must configure in Google Cloud Console) once many
independent installs write into one shared Drive/Sheets destination.

## Quick start (development)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

copy config\settings.example.yaml config\settings.local.yaml
# edit config\settings.local.yaml: watch_folder, drive.root_folder_id, sheets.spreadsheet_id

python -m instacore_sync
```

Google Drive/Sheets access requires a `config/credentials.json` OAuth client
— see [`docs/GOOGLE_API_SETUP.md`](docs/GOOGLE_API_SETUP.md). Until that's in
place, the app still runs: the dashboard shows "Google: Sign-in required"
and videos queue up (or route to Needs Review if OCR isn't configured
either) rather than crashing.

## Running the tests

```powershell
pip install -r requirements-dev.txt
pytest -q
ruff check src tests
```

The suite (141 tests) covers Device ID OCR/regex logic (including boundary
cases like `IC-1888` not matching `IC-188`), multi-variant frame
preprocessing and rotation correction, SHA-256 hashing and dedup — including
a concurrent-claim race test — the SQLite repositories, the async upload
worker pool's retry/backoff behavior (with a regression test for
retry-state persistence across the backoff window), Drive/Sheets clients
(mocked, no network needed, including folder-cache eviction and row-index
caching), credential encryption round-trips, spreadsheet formula-injection
sanitization, pause/resume/retry pipeline controls, real `VideoProcessor`
runs against corrupted/zero-byte video files, and full pipeline runs (happy
path, low-confidence → Needs Review, no-match → Needs Review, duplicate
skip) — plus a concurrency stress test that drives dozens of videos through
the real async worker pool under induced random failures. All with faked
external services so CI needs no real Google credentials, Tesseract binary,
or WhatsApp folder.

## Building the Windows installer

```powershell
packaging\build.bat
```

See [`docs/PACKAGING.md`](docs/PACKAGING.md) for details, PyInstaller
options, and the Inno Setup installer script.

## License

Proprietary — internal tool for Career Ops Intel.

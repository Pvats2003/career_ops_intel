# Setup Guide

This guide gets InstaCore Sync running from source on Windows 10/11. For a
packaged, double-click installer see [`PACKAGING.md`](PACKAGING.md); for
Google Drive/Sheets access see [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md).

## 1. Prerequisites

- **Windows 10/11**, 64-bit.
- **Python 3.12** — install from [python.org](https://www.python.org/downloads/)
  or `winget install Python.Python.3.12`. Check "Add to PATH" during install.
- **Tesseract OCR** (if using the default `tesseract` OCR engine) — install
  from the [UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki)
  and note the install path (usually `C:\Program Files\Tesseract-OCR\tesseract.exe`).
  PaddleOCR needs no separate binary — it's a pure pip install (see below).
- **Git** (optional, only if cloning rather than copying the project folder).
- A **WhatsApp Desktop** installation whose "Save to" / downloads folder you
  know (Settings → Chats → Media visibility, or just check where videos land
  by default: `%USERPROFILE%\Documents\WhatsApp Images\WhatsApp Video`, or
  wherever you've configured it).

## 2. Get the code and create a virtual environment

```powershell
cd whatsapp_video_automation
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs the runtime dependencies plus test/lint
tooling (`pytest`, `ruff`, `mypy`). For a leaner install, use
`pip install -r requirements.txt` instead.

> **PaddleOCR note:** `paddlepaddle`/`paddleocr` are sizeable (~200-400 MB
> combined with model downloads). If you only plan to use the Tesseract
> engine, you can skip them — the app detects PaddleOCR is unavailable and
> falls back gracefully (its status shows "Unavailable" in the top bar, and
> `ocr.engine: tesseract` in settings avoids ever calling it).

## 3. Configure settings

```powershell
copy config\settings.example.yaml config\settings.local.yaml
notepad config\settings.local.yaml
```

At minimum, set:

| Key | Meaning |
|---|---|
| `watch_folder` | The WhatsApp Desktop video download folder to watch |
| `drive.root_folder_id` | The Drive folder that will hold each day's dated subfolder (see below) |
| `sheets.spreadsheet_id` | The Google Sheet to write upload rows into |
| `ocr.tesseract_cmd` | Full path to `tesseract.exe`, only if it's not on PATH |

Everything else has a sane default and can also be changed later from the
in-app **Settings** screen (which writes back to this same file).

### Finding a Google Drive folder ID / Sheet ID

Open the folder or spreadsheet in a browser; the ID is the long token in the
URL:

```
https://drive.google.com/drive/folders/1AbCDefGhIJkLmnOPqrsTUvwXYZ012345
                                        └──────────── this part ─────────┘

https://docs.google.com/spreadsheets/d/1AbCDefGhIJkLmnOPqrsTUvwXYZ012345/edit
                                        └──────────── this part ─────────┘
```

## 4. Set up Google API access

Follow [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md) to create OAuth
credentials and drop `credentials.json` into `config/`. The app runs without
this — it just can't upload or write to Sheets until it's done, and the top
bar will show "Google: Sign-in required".

## 5. Run it

```powershell
python -m instacore_sync
```

On first run with Drive credentials configured, a browser window opens for
Google sign-in; after that, the refresh token is cached in `config/token.json`
and sign-in is silent.

Drop a test `.mp4` into your configured `watch_folder` and watch the
Dashboard: it should appear as "Discovered" → "Hashing" → "Reading ID" →
"Uploading" → disappear from the active queue as "Completed" (or route to
**Needs Review** if the Device ID couldn't be read confidently).

## 6. Where the app stores its data

InstaCore Sync never writes inside the project folder at runtime (aside from
`config/settings.local.yaml`, `config/credentials.json`, and `config/token.json`,
all git-ignored). Everything else lives under:

```
%LOCALAPPDATA%\InstacoreSync\
├── instacore_sync.db      SQLite database (jobs, logs, dedup index)
├── Processed\               successfully uploaded videos land here
├── NeedsReview\             low/zero-confidence OCR videos land here
├── Failed\                  videos that exhausted upload retries
└── logs\
    └── instacore_sync.log  rotating structured JSON log (developer diagnostics)
```

## 7. Common issues

| Symptom | Fix |
|---|---|
| "OCR (tesseract): Unavailable" in the top bar | Install Tesseract OCR and/or set `ocr.tesseract_cmd` in Settings |
| "Google: Sign-in required" never clears | `config/credentials.json` missing/invalid — see `GOOGLE_API_SETUP.md` |
| Videos stay in "Queued" forever | Check the Live Log panel on the Dashboard; a stuck OAuth consent window is the usual cause |
| A video never gets picked up | Confirm `watch_folder` in Settings matches WhatsApp Desktop's actual download folder; the app also does a 15s reconciliation sweep in case a filesystem event was missed |
| "Database is locked" errors under heavy load | Shouldn't happen (WAL mode + serialized writes) — if it does, file a bug with the log excerpt |

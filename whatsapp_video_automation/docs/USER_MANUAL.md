# User Manual

A reference for every screen in InstaCore Sync. For first-time setup, see
[`QUICK_START.md`](QUICK_START.md) instead — this document assumes setup
is already done.

> Screenshot placeholders (📷) mark where an image from a real Windows
> install belongs — see the note in [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md).

## The sidebar

Six pages, always visible on the left: **Dashboard**, **Upload Queue**,
**Needs Review**, **Logs**, **Health Check**, **Settings**. The top bar
above the page area shows three live status indicators — Folder Watcher,
Google Account, OCR Engine — plus a **Pause/Resume Uploads** button.

📷 *Screenshot: the full app window with the sidebar and top bar labeled.*

## Dashboard

An at-a-glance view of today's activity: how many videos are waiting,
uploading, completed, failed, or need review; the average OCR confidence;
current transfer speed and estimated time remaining for what's in
progress.

## Upload Queue

Every video currently known to the pipeline, with its status, Device ID,
OCR confidence, and progress. Each row has a **Retry** button, useful
after fixing whatever made a video fail (a Drive permission problem, a
temporary network outage) — it re-queues that one video without
restarting the whole app.

## Needs Review

Videos OCR couldn't confidently read a Device ID from. Click **Resolve…**
on any row to see a thumbnail from the video, the raw text OCR did
manage to read, and a field to type the correct Device ID by hand — this
skips OCR entirely and sends the video straight to upload.

📷 *Screenshot: the Needs Review dialog with a thumbnail and manual entry
field.*

## Logs

A searchable, filterable history of every video InstaCore Sync has ever
finished processing — status, Device ID, OCR confidence and engine used,
Drive link, error message if any, and per-stage timing (how long OCR,
the upload, and the whole job took). Exportable to CSV.

## Health Check

Runs ten checks and shows each as **PASS**, **WARNING**, or **FAILED**
with a plain-language suggested fix:

| Check | What it means |
|---|---|
| Internet | Can reach Google's API servers |
| Google Authentication | Signed in to Google |
| Google Drive | Your configured Drive folder is accessible |
| Google Sheets | Your configured spreadsheet is accessible (or none configured, which is fine) |
| OCR Engine | Tesseract (or PaddleOCR) is installed and ready |
| Disk Space | Enough free space to keep processing videos |
| Folder Permissions | WhatsApp/Processed/Needs Review/Failed folders all exist and are writable |
| Database | The local database is reachable |
| Folder Watcher | Actively watching your WhatsApp folder |
| Background Workers | The upload pipeline is running |

It runs automatically the first time you open the page, and again
whenever you click **Run Health Check**. This is always the first place
to look if something seems wrong — see also
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

📷 *Screenshot: the Health Check page with a mix of PASS/WARNING/FAILED rows.*

## Settings

### General

Theme, launch-at-Windows-startup, desktop notifications, minimize-to-tray,
log level, how long completed history is kept, and **Run Setup Wizard
Again** (re-opens the guided setup from `QUICK_START.md`, useful if you
skipped a step originally).

### Folders

WhatsApp, Processed, Needs Review, and Failed folder paths.

### Google Drive

Root folder ID, an optional Shared Drive ID, the date-folder naming
format, whether uploaded files get "Anyone with the link" sharing, the
path to `credentials.json`, and a **Sign in with Google…** button.

### Google Sheets

Spreadsheet ID, worksheet name, header row, and which column each field
(Date, Device ID, Filename, Drive Link, Status, Uploaded At, OCR
Confidence) goes into.

### OCR Engine

Tesseract / PaddleOCR / Auto (try both, keep the best result), minimum
confidence threshold, how many seconds of video to scan, frame sampling
interval, whether to fall back to scanning the whole video if the opening
seconds are inconclusive, the `tesseract.exe` path (only needed if it's
not on your system PATH), and the Device ID pattern (a regular
expression — the default matches `IC-` followed by 1-5 digits).

### Uploads

How many uploads run at once, retry attempts and backoff, upload chunk
size, and whether duplicate videos (matched by content, not filename) are
skipped automatically.

### Backup and restore (footer buttons, bottom of every Settings tab)

- **Export Settings… / Import Settings…** — just your configuration
  (folders, IDs, OCR/upload options), not your data. Useful for copying
  settings between machines.
- **Backup Now…** — a full backup: settings, the database (your entire
  upload history and anything currently in the queue), and logs, zipped
  into one file. InstaCore Sync also does this automatically once a week
  (configurable in `settings.local.yaml`).
- **Restore from Backup…** — restores all three from a backup file.
  Requires restarting the app afterward.

See [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) for when and how to use
these.

## System tray

If your system tray is available, InstaCore Sync's icon appears there.
Desktop notifications for failures and Needs Review items pop up from
there (toggle in Settings → General). If "minimize to tray" is on,
closing the window hides it instead of quitting — reopen from the tray
icon or Start Menu.

## Safe Mode

If InstaCore Sync can't start normally (a corrupted settings file, a
database problem), it opens in a reduced **Safe Mode** window instead of
crashing — see [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md#safe-mode) for
what to do there.

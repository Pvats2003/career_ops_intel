# InstaCore Sync v1.0.0 — Release Notes

**Release date:** first production release
**Who this is for:** anyone installing InstaCore Sync from the Windows
installer, not just the original developer/operator.

## What InstaCore Sync does

Watches your WhatsApp Desktop download folder, reads the Device ID off
each Instacore screen-recording with OCR, uploads the video to the right
dated folder in Google Drive, logs it to Google Sheets, and files it away
— automatically, continuously, with retries and duplicate protection.

## What's new in this release

This is the first release built for installation by someone other than
the original developer. If you're upgrading a hand-run development copy,
here's what changed:

- **Guided first-run setup.** The first time you open the app, a
  step-by-step wizard walks you through picking your WhatsApp folder,
  signing in to Google, choosing your Drive folder and Sheet, and testing
  that OCR and uploads actually work — before you're left to figure out
  Settings on your own.
- **A Health Check page.** Open it any time to see, at a glance, whether
  your internet, Google Drive, Google Sheets, OCR engine, disk space,
  folder permissions, database, and background workers are all healthy —
  with a plain-language suggested fix for anything that isn't.
- **Safe Mode.** If something is wrong when the app starts (a bad
  setting, a permissions problem), it no longer crashes — it opens in a
  reduced Safe Mode so you can fix the problem and get going again.
- **Backups.** The app now automatically backs up your settings,
  database, and logs, and you can restore from a backup or trigger one
  manually from Settings.
- **A real installer.** Desktop shortcut, Start Menu entry, an
  uninstaller, an option to launch automatically with Windows, and a
  check for whether Tesseract OCR is installed (with a direct link if
  it isn't).
- **Faster, more reliable uploads under real daily use**, including
  fixes so a temporary Google API hiccup no longer wastes a full
  re-upload, and so two videos never silently duplicate each other even
  if several people on a team are running the app against the same
  shared Drive folder and Sheet.

## Before you install

You'll need:
1. **Windows 10 or 11.**
2. **A Google account** with access to the Drive folder and Sheet you
   want InstaCore Sync to use.
3. **Tesseract OCR** (free, third-party) — the installer will tell you if
   it's missing; download it from
   [the UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki).
4. **Google API credentials** (`credentials.json`) — see
   `docs/GOOGLE_API_SETUP.md` or the in-app first-run wizard, which links
   you to the right place.

See `docs/QUICK_START.md` for the fastest path from "just installed" to
"first video processed."

## Known limitations in this release

- The Windows installer (`packaging/installer.iss`) has been reviewed
  line by line but **has not been compiled or run on a real Windows
  machine** as part of producing this release — do that once before
  distributing it. See `docs/QA_REPORT.md`.
- Rolling this out to a team sharing one Google Drive/Sheets destination
  needs a Google Cloud Console change (publishing the OAuth consent
  screen as "Internal") before more than ~100 people can sign in — see
  `docs/DEPLOYMENT_AT_SCALE.md`.
- There is no auto-updater yet; installing a future version means running
  a new installer.

Full technical changelog: `CHANGELOG.md`. Full list of known issues and
their severity: `docs/QA_REPORT.md`.

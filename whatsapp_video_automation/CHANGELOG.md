# Changelog

All notable changes to InstaCore Sync are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/); versioning
follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

## [Unreleased]

Nothing yet.

## [1.0.0] — First production release

The first release intended for installation by non-technical users, not
just the original single-operator development use. Everything below
shipped in this version — there is no prior public release to diff
against, so this entry summarizes the complete feature set rather than a
delta.

### Added

**Core pipeline**
- Zero-touch WhatsApp folder watching (real-time via `watchdog` + a
  periodic reconciliation sweep so no video is ever silently missed).
- Multi-engine OCR (Tesseract / PaddleOCR / Auto) with multi-variant
  preprocessing, rotation correction, and blank-frame pre-filtering.
- Bounded-concurrency async upload pipeline to Google Drive with
  exponential-backoff retry that doesn't block other uploads mid-backoff.
- Google Sheets logging with atomic row placement (`values.append`) safe
  under many concurrent writers.
- SHA-256 deduplication, including a cross-process check (a Drive-native
  `sha256` file property search) so a video forwarded to several team
  members sharing one destination is never uploaded twice.
- Self-healing Drive folder-creation: concurrent installs racing to
  create the same date/device folder converge on one canonical folder.

**Reliability & security**
- Encrypted OAuth token at rest (Windows DPAPI, Fernet fallback).
- Spreadsheet formula-injection sanitization on every Sheets write.
- Device ID pattern validation before any Drive/Sheets write.
- Transient Google API errors (429/500/502/503) now genuinely retry at
  the single-call level.
- Explicit, user-initiated Google sign-in — startup never silently opens
  a browser and blocks the pipeline.
- Safe Mode: a startup failure (bad config, DB migration failure, a
  service that can't initialize) opens a minimal recovery window instead
  of crashing, with uploads disabled and Settings still reachable.

**Setup & operations**
- An 8-step first-run wizard (WhatsApp folder → Processed folder →
  Google sign-in → Drive root folder → Google Sheet → OCR test → upload
  test → ready), each step validated before continuing.
- A Health Check page: Internet, Drive, Sheets, OCR, disk space, folder
  permissions, database, folder watcher, background workers, and Google
  auth, each reported PASS/WARNING/FAILED with a suggested fix.
- One-click backup (settings + database + logs) with restore, plus
  automatic periodic backups.
- A Needs Review screen for videos OCR can't confidently read, with
  thumbnail, raw OCR text, and manual Device ID entry.
- Pause/resume uploads and a per-job manual Retry action.
- Desktop notifications for failures and needs-review items.
- Per-stage timing (OCR/upload/total) and full stack traces in the Logs
  view, with CSV export.
- Settings export/import (backup/restore of configuration alone).
- Jobs-table retention pruning so the working table doesn't grow forever
  across months of continuous use.

**Packaging & distribution**
- A real application icon, wired into the Windows .exe, taskbar/window,
  and system tray.
- Windows version-info resource (Explorer Properties → Details shows
  product name, publisher, and version).
- Inno Setup installer: desktop shortcut, Start Menu entry, uninstaller,
  install-location picker, optional auto-launch-at-Windows-startup, and a
  Tesseract-OCR presence check with clear guidance if it's missing.

### Fixed

A number of defects were found and fixed during the hardening passes that
led to this release — including several that would only surface under
real daily-volume or multi-installation use, not casual testing:

- A dedup race that could let two concurrent uploads of identical content
  both go through.
- A retry-persistence gap where a job mid-backoff could look permanently
  failed in the database and never resume after a restart.
- The Google-API retry policy silently never retrying anything (the
  retry predicate was evaluating the wrong exception).
- A regex false-positive in Device ID extraction (`IC-1888` matching the
  pattern for `IC-188`).
- A date-folder-format default with no year, which would collide with
  itself every 365 days.
- Packaged-`.exe` path resolution for `credentials.json`/`token.json`/
  `settings.local.yaml` that only worked running from source, not from
  an actual built installer.

### Known limitations

See `docs/QA_REPORT.md` (Known Issues) and `docs/DEPLOYMENT_AT_SCALE.md`
for what's intentionally out of scope for this release, including the
Google OAuth verification requirement for rollouts beyond ~100 users
outside a single Workspace organization, and the lack of an
auto-updater for redistributing future versions.

# Installation Guide

For a non-technical user installing InstaCore Sync on their own Windows
computer. If you're setting this up for a team, also read
[`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md).

> **Note on screenshots:** this guide was written and verified in a
> Linux-based environment that cannot run the real Windows installer or
> capture real Windows screenshots. Every screenshot placeholder below
> (📷) marks where a picture from an actual Windows installation should
> be added — the described steps and dialogs themselves reflect exactly
> what `packaging/installer.iss` is configured to show, verified by
> reading that script, not by running it.

## Before you start

You need:

1. **Windows 10 or 11** (64-bit).
2. **The installer file**: `InstaCoreSync-Setup-<version>.exe`, built from
   this repository (see [`PACKAGING.md`](PACKAGING.md) if you're building
   it yourself) or provided by whoever set this up for your team.
3. About **500 MB** of free disk space, plus room for the videos
   InstaCore Sync will process day to day.
4. Optionally, **Tesseract OCR** already installed — the installer will
   tell you if it's missing (see step 4 below) and it's also covered in
   the first-run setup wizard, so it's fine to install it either before
   or right after.

You do **not** need administrator rights — the installer installs to a
per-user location when run without them.

## Steps

### 1. Run the installer

Double-click `InstaCoreSync-Setup-<version>.exe`.

📷 *Screenshot: Windows SmartScreen prompt (if the installer isn't yet
code-signed) — click "More info" then "Run anyway".*

### 2. Choose an install location

📷 *Screenshot: the Inno Setup "Select Destination Location" page.*

The default location is fine for almost everyone. If you want to install
somewhere else (e.g. a drive with more free space), click **Browse** and
pick a folder.

### 3. Choose your shortcuts

📷 *Screenshot: the "Select Additional Tasks" page with two checkboxes.*

- **Create a desktop shortcut** — recommended, so you can find and open
  InstaCore Sync easily.
- **Start InstaCore Sync automatically when Windows starts** — turn this
  on if you want it running in the background every time you log in
  (unchecked by default).

### 4. Install

Click **Install**. This copies the application files and, if you don't
already have Tesseract OCR installed, shows a one-time message explaining
that OCR won't work until you install it separately (it's a free,
third-party tool InstaCore Sync uses, not something this installer
bundles) — with a link to download it. You can dismiss this and install
Tesseract later; the app still installs and runs either way.

📷 *Screenshot: the Tesseract-not-found information dialog.*

### 5. Finish

📷 *Screenshot: the "Completing Setup" page with "Launch InstaCore Sync"
checked.*

Leave **Launch InstaCore Sync** checked and click **Finish** — the app
opens, and (the first time) walks you through the
[first-run setup wizard](QUICK_START.md).

## What got installed

- The application, in the folder you chose in step 2.
- A Start Menu entry (**InstaCore Sync**, plus an **Uninstall InstaCore
  Sync** entry in the same group).
- A desktop shortcut, if you checked that box.
- Your data — the database, logs, processed-video folders — lives
  separately, under `%LOCALAPPDATA%\InstacoreSync\`, so uninstalling the
  program later doesn't touch your upload history by default (see
  [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md)).

## Next: Google API credentials

Before InstaCore Sync can upload to Drive or log to Sheets, it needs a
`credentials.json` file from Google Cloud Console. The first-run wizard
prompts for Google sign-in and links to the setup steps; the full
walkthrough is in [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md).

## Uninstalling

Start Menu → InstaCore Sync → **Uninstall InstaCore Sync**, or Windows
Settings → Apps → InstaCore Sync → Uninstall. See
[`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) for exactly what is and isn't
removed.

## Troubleshooting installation

See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md). The most common issue is
Windows SmartScreen warning about an unrecognized publisher (expected for
an internal tool without a paid code-signing certificate) — click "More
info" → "Run anyway".

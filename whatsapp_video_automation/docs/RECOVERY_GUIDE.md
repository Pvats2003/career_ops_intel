# Recovery Guide

What to do when something's actually broken: Safe Mode, backups, and a
full data reset.

## Safe Mode

If InstaCore Sync can't start normally, it opens a small **Safe Mode**
window instead of crashing. You'll see:

- A plain-language summary of what went wrong, and the full technical
  detail below it (useful if you need to ask for help).
- **Open Settings Folder** — opens the folder containing
  `settings.local.yaml` (and, if configured, `credentials.json`) in File
  Explorer.
- **Open Log File** — opens the folder containing InstaCore Sync's log
  file.
- **Reset Settings to Defaults…** — replaces `settings.local.yaml` with
  the built-in default template. Your processed videos, upload history,
  and Google sign-in are **not** affected — only app configuration
  (folders, Drive/Sheets IDs, OCR/upload options). Use this if the
  problem is a bad or corrupted settings file (the single most common
  cause of a Safe Mode launch).
- **Retry Startup** — tries to start normally again, without needing to
  close and reopen the app.
- **Quit** — exits.

**Typical fix:** click **Reset Settings to Defaults…**, confirm, then
click **Retry Startup**. If that doesn't work, click **Open Log File**
and check the most recent entries for the actual error, or see
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

Uploads are always disabled while in Safe Mode — nothing is being
processed until you're back in the normal app.

## Backing up

Settings → **Backup Now…** creates a zip file (settings + database +
logs) under `%LOCALAPPDATA%\InstacoreSync\backups\`. InstaCore Sync also
does this automatically about once a week (the first time the app starts
after the last backup has aged out), keeping the 5 most recent
automatic backups and deleting older ones.

Because the database contains your entire upload history *and* whatever
is currently mid-flight in the queue, a database backup covers both —
there is no separate "queue" file to back up.

## Restoring from a backup

Settings → **Restore from Backup…**, pick the `.zip` file, confirm. This
replaces your current settings, database, and logs with the backup's
contents — **there is no undo**, so if you're unsure, take a fresh
**Backup Now** first so you can restore back to where you started if
needed.

**You must restart InstaCore Sync afterward** — restoring doesn't try to
hot-swap the database out from under a running app, since that would risk
corrupting whatever it's mid-write on.

Restoring works across machines: the backup doesn't include your Google
sign-in (see below), but does include everything else, so you can move
your full upload history to a new computer by copying the backup file
over and restoring it there.

## What's *not* in a backup

- **Google sign-in.** You'll need to sign in again (Settings → Sign in
  with Google) after restoring on a machine that wasn't already signed
  in — this is deliberate, so a backup file never carries live Google
  access with it.
- **`credentials.json`** (the OAuth client file from Google Cloud
  Console). Keep a copy of this yourself if you want to avoid redoing
  the Google Cloud Console setup in [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md)
  after a full uninstall/reinstall — see below.

## Uninstalling — what's kept, what's removed

Running the uninstaller (Start Menu → Uninstall InstaCore Sync) removes:

- The installed application files.
- `config/` next to where the app was installed — `settings.local.yaml`,
  `credentials.json` if you placed one there, and the encrypted
  `token.json`/`token.key`.
- Log files under `%LOCALAPPDATA%\InstacoreSync\logs\`.

It does **not** remove:

- The database (`%LOCALAPPDATA%\InstacoreSync\instacore_sync.db`) — your
  entire upload history and audit trail.
- Your Processed / Needs Review / Failed folders and whatever videos are
  in them.
- Backup files under `%LOCALAPPDATA%\InstacoreSync\backups\`.

This is deliberate: uninstalling the *program* shouldn't silently delete
your *data*. If you reinstall later, your history is still there.

**If you want a completely clean slate** (e.g. before giving the computer
to someone else), also manually delete the
`%LOCALAPPDATA%\InstacoreSync\` folder after uninstalling.

**If you plan to reinstall and don't want to redo Google Cloud Console
setup**, copy `credentials.json` somewhere safe *before* uninstalling —
uninstalling removes it along with the rest of `config/`.

## A corrupted database

If the Health Check page shows the Database check as FAILED and
restarting the app doesn't help:

1. Close InstaCore Sync.
2. If you have a recent backup, restore it (see above).
3. If not, and you're comfortable it's acceptable to lose recent history,
   rename (don't delete, in case you need it later)
   `%LOCALAPPDATA%\InstacoreSync\instacore_sync.db` and its `-wal`/`-shm`
   sidecar files if present, then start InstaCore Sync — it creates a
   fresh, empty database and continues working. Your already-uploaded
   videos are still safely in Google Drive/Sheets regardless; only the
   *local* record of them (the Logs page's history) would be affected.

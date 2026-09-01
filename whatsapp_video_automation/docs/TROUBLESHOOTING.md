# Troubleshooting Guide

Start with the **Health Check** page (sidebar) — it runs the same checks
this guide describes and tells you exactly which one is failing. The
sections below go deeper on each.

## "OCR (tesseract): Unavailable" / OCR shows FAILED

**Cause:** Tesseract OCR isn't installed, or isn't where InstaCore Sync
expects it.

**Fix:**
1. Install it from
   [the UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki)
   (free).
2. Restart InstaCore Sync, or go to Health Check and click **Run Health
   Check** again.
3. If it's still not found and you installed it somewhere other than
   `C:\Program Files\Tesseract-OCR\`, go to Settings → OCR Engine and set
   the **tesseract.exe path** explicitly.

## "Google: Sign-in required"

**Cause:** Not signed in, or a previous sign-in expired.

**Fix:** Settings → Google Drive → **Sign in with Google…**. This opens
your browser — approve access, then check the status indicator at the
top of the app updates to show your account.

If a browser window doesn't open, check that you have a default browser
set in Windows.

## Videos aren't being picked up at all

**Cause:** almost always the WhatsApp folder path is wrong, or that
folder isn't accessible.

**Fix:**
1. Health Check → check the **Folder Watcher** and **Folder Permissions**
   rows.
2. Settings → Folders → confirm the **WhatsApp folder** path is exactly
   where WhatsApp Desktop actually saves videos (open that folder in File
   Explorer and compare).
3. If you recently changed WhatsApp Desktop's download location, update
   the setting to match, then restart InstaCore Sync (folder changes take
   effect on the next pipeline start).

## A video is stuck in "Needs Review"

**Cause:** OCR couldn't confidently read a Device ID from the video's
opening frames — a genuinely unreadable frame (bad lighting, unusual
camera angle, the Device ID banner not visible early enough), not
necessarily a bug.

**Fix:** Needs Review page → **Resolve…** on that video → type the
correct Device ID by hand. This routes straight to upload without
re-running OCR.

If this is happening often, Settings → OCR Engine → try lowering the
**minimum confidence** threshold slightly, or switch to **Auto** mode
(tries both OCR engines and keeps the better result) if PaddleOCR is
also installed.

## Uploads keep failing

**Fix, in order:**
1. Health Check → **Internet** and **Google Drive** rows — confirms
   connectivity and that your configured folder is actually reachable.
2. Check the **Logs** page for the specific error message on the failed
   video — it's usually self-explanatory (permission denied, quota
   exceeded, folder not found).
3. Upload Queue → click **Retry** on the failed video once the underlying
   problem (network, permissions) is fixed — no need to restart the app.
4. A permission error specifically means your Google account doesn't
   have edit access to the configured Drive folder — confirm with
   whoever owns that folder.

## "Disk Space" shows WARNING or FAILED

**Cause:** the drive holding your WhatsApp/Processed folders is close to
full — under about 2 GB free triggers a warning, under 200 MB fails.

**Fix:** free up space, or point your Processed folder (Settings →
Folders) at a drive with more room. Videos can't be safely written or
moved with almost no space left.

## The app won't start / opens in Safe Mode

See [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md#safe-mode) — the short
version: click **Reset Settings to Defaults…**, then **Retry Startup**.

## Windows SmartScreen blocks the installer

**Cause:** the installer isn't signed with a paid code-signing
certificate (common for an internal tool). This is a warning, not
evidence of a real problem, if the installer came from a trusted source
on your team.

**Fix:** click **More info**, then **Run anyway**.

## The system tray icon is missing or blank

**Cause:** either your Windows system tray isn't available in the
current session (rare — e.g. some remote desktop configurations), or the
app's icon asset wasn't bundled correctly in this build.

**Fix:** the app still works fully without a tray icon — this only
affects the "minimize to tray" and desktop-notification conveniences.
Confirm Settings → General → "Minimize to system tray" is what you
expect; if the icon is genuinely blank rather than absent, that's worth
reporting (see below).

## Still stuck?

1. Settings → General → note your version number (shown under "InstaCore
   Sync" in the sidebar).
2. Health Check page → note which checks fail.
3. Open the log file (Safe Mode's "Open Log File" button, or
   `%LOCALAPPDATA%\InstacoreSync\logs\`) and look at the most recent
   entries.
4. See [`FAQ.md`](FAQ.md), or report the issue with the above details to
   whoever maintains this tool for your team.

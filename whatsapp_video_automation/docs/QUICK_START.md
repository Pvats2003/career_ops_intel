# Quick Start

From "just installed" to "first video processed," in one pass through the
first-run setup wizard.

> Screenshots below are marked 📷 with a description in place of an image
> — see the note in [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) on
> why (this guide was written where a real Windows screen can't be
> captured).

## 1. Open InstaCore Sync

The first time you open it, the **setup wizard** appears automatically —
you don't need to find it. If you ever want to run it again (to finish a
step you skipped), it's in **Settings → Run Setup Wizard Again**.

Every step below is validated for real before you can continue — but
every step also has a **Skip for now** option, so nothing can trap you if
one piece (like Tesseract OCR) isn't ready yet. Skipped items just show
up later as things to fix on the [Health Check page](USER_MANUAL.md#health-check).

📷 *Screenshot: the wizard's page 1, "Welcome to InstaCore Sync."*

## 2. Step 1 — WhatsApp Download Folder

Point this at wherever WhatsApp Desktop saves videos it downloads — often
your Downloads folder, or WhatsApp's own Media subfolder. Click **Browse**
to pick it. The wizard checks the folder exists and is writable before
letting you continue.

## 3. Step 2 — Processed Folder

Pick a different folder for InstaCore Sync to move videos into once
they're successfully uploaded. This keeps your WhatsApp folder from
filling up with videos that have already been handled.

## 4. Step 3 — Sign in to Google

Click **Sign in with Google…** — this opens your browser to Google's own
sign-in page. Approve access to Drive and Sheets, then come back to
InstaCore Sync; the page updates automatically once you're signed in.

📷 *Screenshot: the Google OAuth consent screen in the browser.*

## 5. Step 4 — Google Drive Destination

Open the Google Drive folder you want videos uploaded into, copy its ID
from the web address bar (the part after `/folders/`), and paste it in.
Click **Verify Folder** — InstaCore Sync checks it's real and accessible
before letting you continue.

## 6. Step 5 — Google Sheets Log (optional)

Same idea, for the spreadsheet you want every upload logged to. This step
is optional — skip it if you don't need a log.

## 7. Step 6 — Test OCR

Click **Test OCR** to confirm the OCR engine that reads Device IDs off
your videos is installed and working. If it isn't yet (Tesseract not
installed), skip this and install it later — see
[`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md) for Google-side setup and the
[Troubleshooting guide](TROUBLESHOOTING.md#ocr-shows-unavailable) for OCR.

## 8. Step 7 — Test Upload

Click **Test Upload** — InstaCore Sync uploads a small test file to your
configured Drive folder and immediately deletes it, proving sign-in +
Drive access actually work end to end, not just that the folder ID looks
valid.

## 9. Step 8 — Ready

A summary of everything you configured (and anything you skipped). Click
**Finish** to save it and start using InstaCore Sync.

📷 *Screenshot: the wizard's final "Ready" page with the summary.*

## 10. Send yourself a test video

Forward or send yourself an Instacore screen-recording in WhatsApp, on
the account InstaCore Sync is watching. Within a few seconds it should
appear on the **Dashboard** and **Upload Queue** pages, then move to
**Processed** once it's uploaded.

📷 *Screenshot: the Dashboard showing one video in progress.*

If nothing happens, open the **Health Check** page from the sidebar — it
checks Internet, Google Drive, Google Sheets, OCR, disk space, folder
permissions, the database, the folder watcher, and background workers,
and tells you exactly what's wrong and how to fix it.

## What's next

- [`docs/USER_MANUAL.md`](USER_MANUAL.md) — every screen, explained.
- [`docs/FAQ.md`](FAQ.md) — common questions.
- [`docs/TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — when something isn't
  working.

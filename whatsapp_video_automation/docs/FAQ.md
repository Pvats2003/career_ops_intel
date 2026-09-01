# Frequently Asked Questions

**Does InstaCore Sync need to stay open to work?**
Yes — it watches your WhatsApp folder and processes videos while running.
Turn on Settings → General → "Minimize to system tray" so closing the
window keeps it running in the background instead of quitting, and
"Launch automatically when Windows starts" if you want it always running
without having to open it yourself.

**Will it upload the same video twice?**
No. Every video is checked by content (a SHA-256 hash), not filename —
even if it arrives again under a different name, or gets forwarded to you
twice, it's recognized as a duplicate and skipped, not re-uploaded.

**What happens if my computer restarts or loses power mid-upload?**
Nothing is lost. Whatever was in progress resumes automatically the next
time InstaCore Sync starts — that's exactly what the Upload Queue and the
database are for.

**Does it delete my WhatsApp videos?**
No — it *moves* a video out of your WhatsApp folder only after it's
successfully uploaded (into your configured Processed folder), or into
Needs Review / Failed if something went wrong. It never deletes a video.

**Can I pause it?**
Yes — the **Pause Uploads** button at the top of the app stops new
uploads from starting; anything already in progress finishes normally.
Click **Resume Uploads** to continue.

**Do I need a Google Sheet?**
No — it's optional. Skip that step in setup if you only want videos
uploaded to Drive without a spreadsheet log.

**Can several people use InstaCore Sync against the same Drive folder
and Sheet?**
Yes, that's a supported setup, with real protection against duplicate
uploads and row collisions even when many people's copies of the app are
running against the same shared destination at once. If you're setting
this up for a team, read [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) —
there's an important one-time Google Cloud Console step (publishing the
sign-in screen as "Internal") needed once you're past about 100 users.

**Is my Google sign-in stored safely?**
Yes — it's encrypted on disk using Windows' own credential protection
(the same mechanism Chrome and Windows Credential Manager use), never
stored as plain text. See [`SECURITY.md`](SECURITY.md) for the full
picture, including what this protection does *not* cover (mainly: anyone
who can log into your Windows account can use the app's already-signed-in
session, the same as any desktop app).

**What does "Auto" OCR mode do?**
Runs both Tesseract and PaddleOCR (if both are installed) and keeps
whichever produces a higher-confidence, correctly-formatted result. Often
more accurate than either alone, at the cost of being slower per video.

**A video's Device ID is wrong — can I fix it after upload?**
Not from within the app — by the time a video is uploaded and logged,
InstaCore Sync doesn't edit past records. Fix it directly in Drive
(rename/move the file) and in the Sheet row if you're using one.

**Where's my data stored?**
`%LOCALAPPDATA%\InstacoreSync\` — the database, logs, and backups. Your
actual settings file and Google credentials live next to wherever the
app is installed. See [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) for the
full breakdown, including what an uninstall does and doesn't remove.

**How do I move InstaCore Sync to a new computer?**
Settings → **Backup Now…** on the old machine, copy the resulting `.zip`
to the new one (installed and set up there first), then Settings →
**Restore from Backup…**. You'll need to sign in to Google again on the
new machine — sign-in is deliberately not included in backups.

**Something crashed / won't open. What do I do?**
It shouldn't — InstaCore Sync is designed to open in a reduced Safe Mode
rather than crash outright if something's wrong at startup. See
[`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md#safe-mode). For anything else,
see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

# Deploying to a Team (500 Users, One Shared Destination)

InstaCore Sync was built and originally hardened (see `docs/SECURITY.md`
and the project history) as a **single-operator desktop tool**: one
person, one machine, one Google account, one local SQLite database. This
document covers what changes — in the code, and in what you must do
operationally — when the deployment model becomes **500 independent
installs, each on its own team member's machine, all writing into the
same shared Google Drive folder tree and the same Google Sheet**.

That second part is the load-bearing detail. It's the difference between
"500 people each using their own copy of a tool" (embarrassingly
parallel, nothing to coordinate) and "500 processes with no channel to
talk to each other, all mutating the same two pieces of shared state at
once" (a real distributed-systems problem). Everything below is written
for that second, harder scenario.

## What the code now guarantees under concurrent writers

These were fixed in this pass and are covered by dedicated concurrency
tests (`tests/unit/test_sheets_client.py::test_concurrent_new_rows_...`,
`tests/unit/test_drive_client.py::test_concurrent_folder_creation_...`) —
not just unit tests of the logic in isolation, but tests that actually
drive many independent client instances against one shared fake backend
concurrently, because that's the class of bug that only shows up under
real interleaving.

- **New Sheet rows never collide.** Row placement uses Sheets' own
  `values.append` (server-side, atomic) instead of a client-computed
  "next row" — two processes appending around the same moment can no
  longer be assigned the same row and silently overwrite each other.
- **Drive folder duplication is self-healing.** Drive has no atomic
  "create if not exists," so two processes can still both create
  `"1 Sep 2026/IC-188"` in the same instant — but every process now
  re-checks after creating, deterministically agrees on one canonical
  folder (oldest `createdTime`), and trashes its own losing, still-empty
  folder. All processes converge on the same folder without needing to
  coordinate.
- **Duplicate uploads across different people's machines are caught.**
  The local `uploaded_hashes` SQLite table only ever knew what *that one
  process* had uploaded — worthless when the same video gets forwarded to
  five different team members, each running their own copy with an empty
  local index for it. Every upload now tags its file with a `sha256`
  custom Drive property; before uploading, a process that misses locally
  asks Drive itself whether that hash exists anywhere in the shared
  destination. This fails open (a Drive-side error never blocks a
  legitimate upload) and backfills the local cache on a hit.
- **Transient Drive/Sheets errors (429/500/502/503) now actually retry**
  at the single-API-call level. This was silently broken before this pass
  — every `@google_api_retry()`-decorated method converts the raw
  `HttpError` into a typed `DriveApiError`/`SheetsApiError` before
  returning, and the retry predicate was only ever being shown that typed
  wrapper, which it can't classify (no `.resp`), so it never retried
  anything. At 500-user scale, where combined API traffic makes hitting a
  rate limit routine rather than rare, this matters far more than it did
  for one operator.
- **Startup no longer hangs waiting on a browser nobody asked for.**
  `PipelineOrchestrator.start()` used to call the *interactive* OAuth
  flow unconditionally — for any of the 500 installs without a valid
  stored token (first run, an expired refresh token, a revoked grant),
  the entire pipeline (folder watcher, upload pool, everything) would
  simply never start. Startup now only ever attempts a silent
  refresh/fail; a real browser consent screen only opens from an explicit
  "Sign in with Google" button in Settings.
- **The packaged .exe now resolves `credentials.json`/`token.json`/
  `settings.local.yaml` correctly.** The previous path logic
  (`Path(__file__).resolve().parents[3]`) only meant something for a
  source checkout — inside a PyInstaller bundle it resolved to nothing
  meaningful, which would have broken sign-in persistence for every one
  of the 500 packaged installs the moment someone actually built and ran
  the shipped .exe rather than `python -m instacore_sync` from source.

### Residual risk windows (be honest about what's still true)

- Drive folder reconciliation resolves duplicates *after* they're
  created, not before — there is a real (small, self-correcting) window
  where two folders briefly coexist. If a video is somehow uploaded into
  a losing folder in that window (would require a second, independent
  race on top of the first), it stays there; reconciliation only ever
  trashes an empty folder it just created itself, by design, so it will
  never delete an uploaded video.
- The cross-process Drive-hash dedup check is one extra `files.list` call
  per video that isn't already a local hit — i.e. most videos, most of
  the time. At 150-500 videos/user/day × 500 users this is a real,
  bounded addition to daily Drive API call volume (see quota notes
  below), traded deliberately for closing an otherwise-silent duplicate-
  upload gap.
- None of this makes the local SQLite `jobs`/`upload_logs` tables shared
  — each user's Queue/Logs view only ever shows *their own* machine's
  activity. There is no cross-team dashboard. If that's wanted, it's a
  new feature (a shared log — the Sheet — already exists; a shared queue
  view does not), not a hardening fix.

## The blocker you cannot code your way around: OAuth verification

This is the single most important thing to resolve before a 500-user
rollout, and it happens in the Google Cloud Console, not in this
repository.

The app requests the `drive` scope (broad — needed for the folder
create/list operations this whole design depends on) and `spreadsheets`.
Google classifies `drive` as a **restricted scope**. An OAuth consent
screen in "Testing" publishing status is hard-capped at **100 test
users** — the 101st team member's sign-in will simply be rejected by
Google, not by this app.

Two real paths forward, in order of how fast they actually are:

1. **If all 500 users are in the same Google Workspace organization**
   (this being "a team," that's the likely case): publish the OAuth
   consent screen as **Internal** in Google Cloud Console. Internal apps
   are exempt from both the 100-user cap and the CASA security-assessment
   verification process entirely — this is almost certainly the answer,
   and it's a Google Cloud Console setting change, not a code change.
2. **If users span multiple Google accounts/organizations** (personal
   Gmail accounts, mixed domains): the consent screen must go through
   full external verification, which for a restricted scope like `drive`
   includes a CASA security assessment — a genuinely slow (weeks),
   external, and non-free process. The faster alternative is narrowing
   the requested scope to `drive.file` (unrestricted, no CASA needed),
   but `drive.file` only grants the app access to files/folders *it
   itself created* or that the user explicitly picked via a Google
   Picker dialog — since the shared root folder here is pre-created by
   an admin and shared to everyone, `drive.file` alone would not let the
   app see into it. Making that work requires adding a one-time
   Picker-based "select your team's destination folder" step to the app
   (a real feature: an API key, a Picker web view, a local callback) —
   flagged under Future Recommendations below, not implemented in this
   pass, because it changes the sign-in UX and shouldn't be done as a
   drive-by scope change.

Do not attempt to route around this by embedding a single shared service
account credential in the distributed app instead of per-user OAuth: a
static credential baked into (or shipped alongside) 500 copies of a
desktop app is a credential 500 machines' worth of disk access, and
eventually a curious user's decompiler, can extract — it would have
access to the entire shared Drive tree, not scoped to what any one person
should be able to touch. Per-user OAuth, however much more setup it is up
front, is the correct trust boundary here.

## Destination architecture: use a Shared Drive, not someone's My Drive

`DriveSettings.shared_drive_id` already exists and every Drive call in
this codebase already passes `supportsAllDrives=True`/
`includeItemsFromAllDrives=True` — Shared Drive support was designed in
from the start. At 500-user scale, actually using it (rather than a
folder living inside one person's personal My Drive, merely shared with
everyone else) stops being optional:

- **Storage quota.** A folder inside someone's My Drive counts against
  *that one person's* storage quota, no matter who uploads into it — 500
  people's worth of video uploads will exhaust a personal/Workspace-seat
  quota fast, and that person becomes a single point of failure the rest
  of the team doesn't control. A Shared Drive's storage is pooled at the
  Workspace/organization level.
- **Durability.** If the owner of a My Drive folder ever leaves the
  organization or has their account suspended, the folder (and everything
  under it) goes with them unless ownership was manually transferred
  first. A Shared Drive has no single owner in that sense.

Set `drive.shared_drive_id` in `config/settings.local.yaml` (every
install) to the target Shared Drive's ID, with `drive.root_folder_id`
pointing at a folder inside it.

## API quota at 500x the traffic

Every Drive/Sheets API quota in this app was tuned assuming one process's
daily volume (150-200, up to 500, videos/day). At 500 independent
processes sharing one destination:

- Google's Drive API quota is generally **per end-user, per 100 seconds**
  for the *querying* account, not shared across users — so 500 different
  people's OAuth-authenticated calls mostly don't compete with each other
  for quota the way 500 threads in one process would. The real new cost
  is the *sum* of daily API calls against the shared destination's
  visibility (folder lookups, the new cross-process hash-dedup search),
  which is now correctly retried on 429/500 (see above) rather than
  failing outright.
- The Sheets API append/update calls against the *one* shared spreadsheet
  are the more realistic bottleneck, since Sheets quotas are partly
  per-document, not just per-user. If day-to-day usage shows Sheets
  throttling under real load, the fix is batching (accumulate a few
  seconds' worth of completed jobs and write them in one `batchUpdate`
  instead of one call per video) — not implemented here since there was
  no real traffic to tune against; treat as a follow-up if it's observed.

## Not solved in this pass (deliberately deferred, not silently missed)

- **No auto-updater.** 500 independent installs of a desktop app with no
  update mechanism means every future fix (including everything in this
  document) has to be manually redistributed and reinstalled 500 times.
  For a rollout at this scale, this stops being a nice-to-have. Building
  one (a version-check-and-download flow, or routing through your
  existing software-deployment tooling/MDM if your organization has one)
  is real, scoped work — recommended as the next major project after
  this hardening pass, not attempted here.
- **No fleet-wide diagnostics/telemetry.** When install #347 has a
  problem, today the only recourse is that person describing what
  happened or screen-sharing. A lightweight, explicit, opt-in "Export
  Diagnostics" button (recent structured logs + basic environment info,
  zipped, for the user to attach to a support message — never anything
  automatic or silent) would meaningfully cut down on back-and-forth at
  this scale. Recommended, not implemented here — it's additive UI work,
  lower priority than the correctness fixes above, and shouldn't be
  rushed into an audit pass focused on concurrency/security/reliability.
- **`drive.file` + Picker-based folder authorization**, as the long-term
  answer to the OAuth-verification blocker for a non-Workspace-internal
  rollout — see above.

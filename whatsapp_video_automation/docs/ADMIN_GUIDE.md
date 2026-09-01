# Administrator Guide

For whoever sets up, distributes, and keeps InstaCore Sync running for a
team — not the end users processing videos day to day (see
[`USER_MANUAL.md`](USER_MANUAL.md) for them).

## One-time setup you'll do

1. **Google Cloud Console project** — create an OAuth client
   (`credentials.json`) and, if the destination Drive/Sheets are shared
   across your team, decide on scope/verification now, not after
   rollout — see
   [`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md#the-blocker-you-cannot-code-your-way-around-oauth-verification).
   Full steps: [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md).
2. **Destination**: if more than a handful of people will write into the
   same Drive folder/Sheet, use a **Shared Drive**, not a folder in
   someone's personal My Drive — see
   [`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md#destination-architecture-use-a-shared-drive-not-someones-my-drive)
   for exactly why (storage quota, ownership durability).
3. **Build the installer** — see [`PACKAGING.md`](PACKAGING.md).
4. **Distribute it** — see "Rolling out to a team" below.

## Rolling out to a team

There is currently **no auto-updater and no central management console**.
Each install is independent: its own local database, its own Google
sign-in, its own settings file. Practically, that means:

- **Initial rollout**: distribute the installer via whatever your
  organization already uses (a shared network location, an internal
  software portal, MDM push if you have it). Each person runs it and
  goes through the first-run wizard themselves (they'll need their own
  Google sign-in).
- **Updates**: there's no in-app "check for updates." A new version means
  redistributing a new installer and having each user (or your
  deployment tooling) run it — Inno Setup installers upgrade in place
  over an existing install without needing an uninstall first.
- **Configuration**: `credentials.json` is the one file every install
  needs — decide whether you'll pre-stage it (place it next to the
  installed .exe as part of your deployment process) or have each user
  download it themselves per [`GOOGLE_API_SETUP.md`](GOOGLE_API_SETUP.md).
  `settings.local.yaml` can similarly be pre-populated (Drive folder ID,
  Sheet ID) so the wizard's later steps are already filled in for users —
  drop a completed `config/settings.local.yaml` next to the installed
  .exe before first launch.

## Monitoring a fleet

There is no cross-machine dashboard. Each person's own **Health Check**
page (sidebar) is the diagnostic surface — ask someone reporting a
problem to check it first and tell you which rows fail; that maps
directly to [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)'s sections.

If you need to check on someone's install remotely, the useful artifacts
are:
- The log file, `%LOCALAPPDATA%\InstacoreSync\logs\instacore_sync.log`
  (structured JSON, one event per line).
- A backup zip (Settings → Backup Now…) — has settings + database +
  recent logs bundled together, useful to have someone send you if you
  need to diagnose something more deeply than the log alone shows.

## Backup policy

Automatic backups run locally on each machine (weekly by default,
configurable via `app.auto_backup_interval_days` in
`settings.local.yaml`; `0` disables them), keeping the 5 most recent.
These are **not** centrally collected — if you want off-machine backup
retention (e.g. for a shared-destination deployment where the local
database matters for audit purposes), that's a process your team needs
to set up separately (e.g. periodically copying each machine's
`%LOCALAPPDATA%\InstacoreSync\backups\` folder somewhere central) — not
something this application does on its own.

## Uninstalling / decommissioning a machine

See [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md#uninstalling--whats-kept-what-s-removed)
for exactly what the uninstaller does and doesn't remove. For a machine
being repurposed or handed to someone else, also manually delete
`%LOCALAPPDATA%\InstacoreSync\` after uninstalling, and revoke that
machine's Google access if it was signed in
(myaccount.google.com → Security → Third-party access).

## Team-scale technical details

Everything about running many independent installs against one shared
Drive/Sheets destination — the OAuth verification requirement, what's
guaranteed under concurrent writers, API quota considerations — is in
[`DEPLOYMENT_AT_SCALE.md`](DEPLOYMENT_AT_SCALE.md). Read that before a
rollout beyond a handful of people.

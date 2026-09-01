# QA Report — v1.0.0

What was actually verified before this release, how, and what is still
open. Written from a Linux sandbox with no access to a Windows machine —
that constraint shapes what's below, and it's called out explicitly
wherever it matters rather than glossed over.

## Post-release hardening pass (concurrency/OCR/security review)

After the initial v1.0.0 QA below, a second, adversarial review pass
specifically targeted concurrency, security, and robustness defects the
first pass's functional testing wouldn't surface. Five parallel reviews
covered every subsystem (core/DB/config, OCR/video/watcher, Drive/Sheets/
upload/pipeline, Qt UI/workers, tests/packaging); every finding was
independently verified against the real code before being fixed — several
initial fix attempts themselves had bugs that were only caught by writing
a real regression test for them (see `RELEASE_NOTES.md`/`CHANGELOG.md`
for the full list). Test count grew 227 → 254; full details, file list,
and honest scoring are in the Engineering Review Report delivered
alongside this release.

## Automated test suite

```
254 passed in ~6.5s   (pytest, tests/unit/ + tests/integration/)
ruff check .          All checks passed
```

Both commands were re-run immediately before writing this report, on the
final commit of this release. Breakdown:

- **29 unit test files** (`tests/unit/`) — one per service/module:
  config, database repositories, OCR/device-ID extraction, hashing,
  dedup, folder watching, Drive/Sheets clients (mocked), upload queue and
  worker pool, token encryption, text sanitization, resource-path
  resolution, health checks, backup/restore, Safe Mode, the first-run
  wizard's startup integration, and version metadata.
- **4 integration test files** (`tests/integration/`) — full video
  processing pipeline (including malformed/corrupt video files),
  pipeline-orchestrator pause/resume/retry controls, and a concurrency
  stress test simulating many simultaneous jobs.
- Every automated test runs headless (`QT_QPA_PLATFORM=offscreen`)
  against a real `QApplication` instance (a session-scoped fixture, not a
  mock), so PySide6 widget construction, signal/slot wiring, and Qt
  object lifetimes are exercised for real, not stubbed out.
- An **autouse** fixture isolates every test's settings file into a
  temp directory, so the suite cannot pollute (or be polluted by) the
  real repository's `config/settings.local.yaml`.

## What was specifically verified for this release (Phases 1–8)

**Frozen-build path resolution** (`test_frozen_build_resource_resolution.py`,
`test_resource_paths.py`) — simulates `sys.frozen = True` /
`sys._MEIPASS` with real copied resource files and asserts the app
resolves its theme stylesheet, database migrations, and icon from the
simulated bundle location, not the source tree. This test methodology
is precise enough that it caught two real defects during this release
(below) rather than passing on faith.

**Startup and Safe Mode** (`test_app_startup_features.py`,
`test_app_safe_mode.py`, `test_safe_mode_window.py`) — constructs the
real `InstacoreSyncApp`/`run_application()` path against a real
`QApplication`, including: normal startup, a forced startup failure
falling through to Safe Mode, Safe Mode's Retry/Reset/Quit actions, and
that Safe Mode disables uploads. These are this release's smoke and
startup tests — they exercise the same code path a real launch does, not
a synthetic shortcut.

**Health Check page** (`test_health_check_service.py`) — all 10 checks
(Internet, Drive, Sheets, OCR, Disk Space, Folder Permissions, Database,
Folder Watcher, Background Workers, Google Auth) individually, plus that
one check raising an exception never blanks the rest of the page.

**Backup/restore** (`test_backup_service.py`) — round-trip create →
restore for settings + SQLite database (via SQLite's own online backup
API, so a WAL-mode DB backs up consistently) + logs, including restoring
onto a machine with no prior state.

**Versioning** (`test_version.py`) — confirms `__version__` is
consistent across the application, and that it's a valid semantic
version string.

**First-run wizard** — each of the 8 pages' validation logic (folder
existence/writability, Google auth state, Drive folder/Sheet
accessibility, live OCR test, live upload test) is covered by the
existing service-layer tests those pages call into
(`drive_client`, `sheets_client`, `pipeline_orchestrator`); the wizard
itself is exercised end-to-end as part of `test_app_startup_features.py`.

## Real defects this release's testing caught

Two were severe enough that, unfixed, the packaged Windows `.exe` would
have been broken on first launch for every user:

1. **Theme stylesheet resolution** (`ui/theme/theme_manager.py`) used
   `Path(__file__).parent`, which does not point at bundled resources
   inside a PyInstaller `.exe` — the app would raise on startup applying
   the theme, before the main window ever appeared.
2. **Database migrations resolution** (`db/database.py`) had the same
   bug — the packaged `.exe` would find zero `.sql` migration files, so
   the database schema would never be created and every DB operation
   would fail with "no such table" from the very first launch.

Both were fixed by routing through a shared `resource_paths.py` helper
that resolves correctly whether running from source or from a frozen
build, and both now have a regression test that would fail again if
either file reverted to `Path(__file__)`-based resolution.

A third, non-crashing but real bug was also fixed during this release: a
pre-existing test-suite hygiene issue where constructing `AppSettings()`
with no settings file present silently seeded a real
`config/settings.local.yaml` into the repository — not a defect in the
shipped application, but a defect in how it had been possible to test it
without noticing pollution. Fixed with the autouse isolation fixture
described above.

## What was reviewed manually but NOT automatically tested

- `packaging/installer.iss` (Inno Setup script) — read line by line,
  including the `[Code]` section's Tesseract-detection logic and the
  settings-seed destination fix (`{app}\config`, matching how the app
  actually resolves that path at runtime — an earlier draft pointed at
  `{userappdata}\InstacoreSync\config`, which would not have matched).
- `packaging/pyinstaller.spec` and `packaging/version_info.txt` — read
  for correctness (icon bundling, `EXE()` version resource wiring,
  `filevers`/`ProductVersion` fields); `version_info.txt` was validated
  with `ast.parse()` only, since `PyInstaller.utils.win32.versioninfo`
  requires `pywin32`, a Windows-only package unavailable in this
  sandbox.

## What could NOT be verified in this environment, and why

This sandbox is Linux-only with no Windows machine, no Inno Setup
compiler, and no real Google OAuth consent flow to click through. These
items are **not implemented-and-unverified** — the code and scripts
exist and were reviewed — they are **untestable from here**, and must be
done once, manually, before distributing this release:

| Item | Why it can't be done here | Who should do it |
|---|---|---|
| Compile `packaging/installer.iss` with Inno Setup | Inno Setup is Windows-only software | Whoever builds the release, on Windows |
| Run the compiled installer end-to-end (shortcuts, uninstaller, install-location picker) | Requires the compiled installer above | Same |
| Build the actual `.exe` via `pyinstaller packaging/pyinstaller.spec` | Running PyInstaller on Linux produces a Linux binary, not a Windows one | Same, on Windows |
| Launch the built `.exe` on a clean Windows 10/11 machine with no prior InstaCore Sync install | No Windows machine available | Same |
| Click through the first-run wizard against a real Google account, real Drive folder, real Sheet | Requires a live OAuth consent screen in a real browser | Same |
| Confirm the system tray icon renders correctly | Requires a real Windows desktop session | Same |
| Capture the documentation screenshots (all docs currently use 📷 placeholders) | Requires the running app on a real Windows desktop | Same |
| Confirm Windows SmartScreen behavior on an unsigned installer | Requires a real Windows machine downloading the file | Same |

None of the above is exotic or high-risk work — every one of them is a
first-run walkthrough of functionality whose *logic* is already covered
by the automated suite. They are listed here because "install and run
it once for real" is a genuinely different check than "the code that
does this passed its unit tests," and this report is not going to
pretend otherwise.

## Known issues

See `CHANGELOG.md`'s "Known limitations" and `RELEASE_NOTES.md`'s "Known
limitations in this release" for the user-facing summary. In full:

1. **Installer not yet compiled/run on Windows** (see table above) — the
   single largest open item before distribution.
2. **No auto-updater.** Distributing a future version means rebuilding
   and redistributing the installer; Inno Setup upgrades in place over
   an existing install, but nothing prompts the user to fetch it.
3. **OAuth verification cap for large shared-destination rollouts.**
   Google's default (unverified, "External") OAuth consent screen caps
   sign-in at ~100 test users. Deployments beyond that, outside a single
   Google Workspace organization, need the "Internal" publishing option
   or Google's verification process — see `docs/DEPLOYMENT_AT_SCALE.md`.
4. **No cross-machine fleet dashboard.** Each install is fully
   independent (own database, own settings, own sign-in); monitoring a
   team's installs is manual (`docs/ADMIN_GUIDE.md#monitoring-a-fleet`).
5. **Documentation screenshots are placeholders.** All 8 user-facing docs
   use 📷 markers instead of real screenshots, since no Windows desktop
   was available to capture them in this environment.
6. **Unsigned installer.** No paid code-signing certificate is applied,
   so Windows SmartScreen will show a warning on first run
   (`docs/TROUBLESHOOTING.md` documents the click-through).
7. **A rare Drive folder-reconciliation race can trash a folder still
   receiving an upload.** Under the specific timing of three-plus
   concurrent installs racing to create the same date/device folder,
   the cleanup step that trashes a losing duplicate folder can — in a
   narrow window — trash one a *different* process just started
   uploading into, because the "is it empty" children check and the
   trash call are two separate API round-trips. Identified during the
   post-release hardening pass; not fixed here because a rushed
   concurrency change to this exact code path (which the earlier audit
   already hardened once) is higher-risk than the defect itself, which
   requires an unlikely three-way timing coincidence to trigger. Needs a
   proper fix (e.g. a lock service or an atomic check-and-trash) before
   very-high-concurrency shared-destination deployments (see
   `docs/DEPLOYMENT_AT_SCALE.md`).
8. **`UploadWorkerPool.stop()` doesn't wait for in-flight uploads to
   actually finish.** It cancels queued/waiting work immediately, but a
   video already uploading inside a worker thread keeps running to
   completion in the background even after `stop()` returns — if the
   pipeline is restarted shortly after (app restart), the orphaned
   thread and the fresh restart's requeue could both act on the same
   job. Low real-world impact (a normal app quit doesn't restart the
   pipeline moments later) but a real gap under rapid restart-for-testing
   or a crash-loop scenario.
9. **Searching Logs by device ID or filename does a full table scan.**
   `upload_logs` is never pruned by design (it's the durable audit
   trail) and its search uses `LIKE '%...%'`, which can't use the
   existing indexes. Fine at today's volume; worth an FTS5 index or
   similar if a single install accumulates years of daily 150-500-video
   history and search starts to feel slow.

None of these block a v1.0.0 release for internal/team use where #1 is
completed first; #3 only matters past ~100 concurrent users on a shared
destination; #7-9 only matter at meaningfully higher scale/concurrency
than a typical team deployment.

## Future improvements (not required for v1.0.0)

- Code-signing certificate to remove the SmartScreen warning.
- An auto-update mechanism (even a simple "check GitHub releases and
  notify" would remove the manual-redistribution burden).
- A lightweight fleet-monitoring option for admins managing many
  installs (e.g. an opt-in periodic health-check upload).
- Real screenshots throughout the documentation set, captured once a
  Windows build environment is available.

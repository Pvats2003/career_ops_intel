# Packaging Guide (Windows)

InstaCore Sync ships to end users as a standalone Windows installer, built
in two stages: **PyInstaller** freezes the Python app into a folder of
`.exe`+DLLs, then **Inno Setup** wraps that folder into a proper
`InstaCoreSync-Setup-<version>.exe` installer with Start Menu / desktop
shortcuts and an optional "run at Windows startup" task.

## Prerequisites

- Everything in [`SETUP.md`](SETUP.md) (Python 3.12, the project's
  dependencies installed).
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed, with `iscc.exe`
  on `PATH` (its installer offers to add it). Optional — skip this if you
  only need the raw PyInstaller build, not a distributable installer.

## One-command build

```powershell
cd whatsapp_video_automation
packaging\build.bat
```

This script:
1. Creates/reuses a `.venv`, installs `requirements.txt` + PyInstaller.
2. Runs the full test suite (`pytest -q`) and **aborts the build if any test
   fails** — a red pipeline never gets packaged.
3. Runs PyInstaller against `packaging/pyinstaller.spec`, producing
   `dist/InstaCoreSync/InstaCoreSync.exe` (a one-folder build, not
   `--onefile` — see "Why one-folder" below).
4. If `iscc` is on PATH, compiles `packaging/installer.iss` into
   `packaging/output/InstaCoreSync-Setup-<version>.exe`.

## Manual steps (equivalent to build.bat)

```powershell
pip install -r requirements.txt pyinstaller
pytest -q
pyinstaller packaging\pyinstaller.spec --clean --noconfirm
iscc packaging\installer.iss
```

## What `pyinstaller.spec` does

- Entry point: `src/instacore_sync/__main__.py`.
- Bundles the QSS theme files and the SQLite migration `.sql` files as
  `datas` (PyInstaller's static analysis can't discover non-Python
  resources loaded via `Path(__file__).parent / "..."`, so they're listed
  explicitly).
- Uses `collect_all()` for `paddleocr`/`paddle` when they're installed, to
  pull in their model/data files — safe to skip if you only ship the
  Tesseract engine (wrap those two packages out of your venv before
  building for a smaller installer).
- `console=False` — no terminal window pops up behind the GUI.
- Looks for `src/instacore_sync/ui/resources/icons/app_icon.ico` and uses it
  as the `.exe` icon if present (see "Adding an icon" below).

### Why one-folder, not `--onefile`

`--onefile` extracts the entire frozen app to a temp directory on *every*
launch, which is slow and — worse — breaks PaddleOCR's model file caching
(it would re-extract multi-hundred-MB model files on every start). The
one-folder `COLLECT(...)` build in the spec avoids both problems; Inno Setup
still gives end users a single-file installer experience.

## Adding an app icon

Drop a `.ico` file at:

```
src/instacore_sync/ui/resources/icons/app_icon.ico
```

`pyinstaller.spec` picks it up automatically (both for the built `.exe` and,
via `installer.iss`, for shortcuts). A 256×256 multi-resolution `.ico` is
recommended; use an online PNG→ICO converter or `magick convert` if you only
have a PNG source.

## What `installer.iss` does

- Installs to `%LOCALAPPDATA%\Programs\InstaCore Sync` by **current user**
  (`PrivilegesRequired=lowest`) — no admin rights needed, matching a
  single-user desktop tool.
- Seeds `%APPDATA%\InstacoreSync\config\settings.local.yaml` from
  `config/settings.example.yaml` **only if the user doesn't already have
  one** (`onlyifdoesntexist`), so re-installing/updating never clobbers a
  user's configuration.
- Optional tasks (both off by default, user-selectable in the installer
  wizard): desktop shortcut, and "start automatically when Windows starts"
  (drops a shortcut in the user's Startup folder — this is the mechanism
  behind the app's own `app.auto_start_with_windows` setting).
- Registers a proper uninstaller (Control Panel → Apps) that also removes
  the app's log directory.

## Verifying a build before shipping it

```powershell
dist\InstaCoreSync\InstaCoreSync.exe
```

Sanity-check: the app launches without a console window, the Dashboard
renders with the dark glass theme, and Settings can be opened and saved.
Then run the installer produced in `packaging\output\` on a clean VM/user
profile if possible — this catches "works on my machine because I have
Tesseract installed globally" class issues.

## Versioning

Bump the version in three places when cutting a release:
- `pyproject.toml` → `[project] version`
- `packaging/installer.iss` → `#define MyAppVersion`
- (optional) tag the commit `vX.Y.Z`

## CI recommendation

If you wire this into a CI pipeline (e.g. GitHub Actions `windows-latest`
runner), run `pytest -q` and `ruff check` as a required check before
triggering `packaging\build.bat`, and upload
`packaging\output\InstaCoreSync-Setup-*.exe` as a release artifact.

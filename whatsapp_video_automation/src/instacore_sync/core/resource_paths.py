"""Where things live on disk, running from source vs. frozen into a
PyInstaller build.

Extracted from `config.py` (which needed this first, for
`credentials.json`/`settings.local.yaml`) because the same two locations
are needed again for the bundled application icon — one shared, tested
implementation rather than two copies quietly drifting apart.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True inside a PyInstaller-built .exe, false running from source."""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    """Where user-writable/user-provided files live, relative to: the
    folder containing the installed .exe when frozen (via `sys.executable`
    — stable across restarts, exactly where docs already tell users to
    place `credentials.json`), or the project root when running from a
    source checkout. See `config.py`'s `_app_base_dir` for the full
    rationale (a module frozen into a PyInstaller bundle has no
    meaningful on-disk `__file__` to walk up from).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/instacore_sync/core/resource_paths.py -> core -> instacore_sync -> src -> project root
    return Path(__file__).resolve().parents[3]


def bundled_resource_dir() -> Path:
    """Where read-only resources PyInstaller bundled alongside the app
    live (the settings.example.yaml seed template, the application icon)
    — always `sys._MEIPASS` when frozen, regardless of PyInstaller's
    internal onefile/onefolder layout; the project root in source-tree
    development.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_base_dir()))
    return Path(__file__).resolve().parents[3]


def icon_path() -> Path:
    """The application icon (.ico) — bundled as a `datas` entry in
    `packaging/pyinstaller.spec` alongside the settings template, so it's
    resolved the same way. Callers (window/tray icon) should check
    `.exists()` before use: this returns where it *should* be, not a
    guarantee it's there (e.g. a dev checkout that hasn't run
    `packaging/generate_icon.py`).
    """
    if is_frozen():
        return bundled_resource_dir() / "instacore_sync" / "ui" / "resources" / "icons" / "app_icon.ico"
    return (
        Path(__file__).resolve().parents[1] / "ui" / "resources" / "icons" / "app_icon.ico"
    )

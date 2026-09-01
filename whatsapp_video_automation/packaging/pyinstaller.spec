# PyInstaller build spec for InstaCore Sync (Windows).
#
# Build with:
#   pyinstaller packaging/pyinstaller.spec --clean --noconfirm
#
# Output: dist/InstaCoreSync/InstaCoreSync.exe (one-folder build — recommended
# over --onefile so PaddleOCR/OpenCV DLLs and models don't have to be
# re-extracted to a temp dir on every launch).

import sys
from pathlib import Path

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).parent
SRC_DIR = PROJECT_ROOT / "src"

datas = [
    (str(PROJECT_ROOT / "src" / "instacore_sync" / "ui" / "theme" / "dark_theme.qss"), "instacore_sync/ui/theme"),
    (str(PROJECT_ROOT / "src" / "instacore_sync" / "ui" / "theme" / "light_theme.qss"), "instacore_sync/ui/theme"),
    (str(PROJECT_ROOT / "src" / "instacore_sync" / "db" / "migrations"), "instacore_sync/db/migrations"),
    (str(PROJECT_ROOT / "config" / "settings.example.yaml"), "config"),
]

# The application icon: embedded into the .exe's own resources via EXE()'s
# `icon=` below (Windows Explorer/taskbar icon), *and* bundled here as a
# plain data file so the running app can load it at runtime too (window
# icon, system tray icon) via resource_paths.icon_path() -- those are two
# separate mechanisms in PyInstaller and both are needed.
_ICON_DIR = PROJECT_ROOT / "src" / "instacore_sync" / "ui" / "resources" / "icons"
if _ICON_DIR.exists():
    datas.append((str(_ICON_DIR), "instacore_sync/ui/resources/icons"))

# PaddleOCR ships model files and non-Python resources that PyInstaller's
# static analysis cannot discover; collect them explicitly when present.
hiddenimports = [
    "pytesseract",
    "google.auth.transport.requests",
    "googleapiclient.discovery",
    "googleapiclient.discovery_cache",
]

try:
    from PyInstaller.utils.hooks import collect_all

    for pkg in ("paddleocr", "paddle"):
        try:
            pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
            datas += pkg_datas
            hiddenimports += pkg_hidden
        except Exception:
            pass  # PaddleOCR is optional; Tesseract-only builds are still valid.
except ImportError:
    pass

a = Analysis(
    [str(SRC_DIR / "instacore_sync" / "__main__.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_ICON_FILE = PROJECT_ROOT / "src" / "instacore_sync" / "ui" / "resources" / "icons" / "app_icon.ico"
_VERSION_FILE = PROJECT_ROOT / "packaging" / "version_info.txt"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InstaCoreSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(_ICON_FILE) if _ICON_FILE.exists() else None,
    # Windows Explorer's file Properties -> Details tab (product name,
    # version, publisher) -- only meaningful on a real Windows build;
    # PyInstaller silently ignores this on other platforms.
    version=str(_VERSION_FILE) if _VERSION_FILE.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="InstaCoreSync",
)

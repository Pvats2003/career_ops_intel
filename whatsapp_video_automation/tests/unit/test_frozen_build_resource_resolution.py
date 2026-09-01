"""Regression tests for a real class of bug found in the release audit:
several modules resolved bundled resources (SQL migrations, QSS theme
files) via `Path(__file__).parent` — correct running from source, but
silently broken once frozen into a PyInstaller build, because a module
bundled into the PYZ archive has no real on-disk `__file__` to resolve a
sibling file against.

`packaging/pyinstaller.spec` bundles these as `datas` entries, which
PyInstaller always exposes under `sys._MEIPASS` when frozen (regardless
of onefile/onefolder layout) — these tests simulate that environment by
setting `sys.frozen`/`sys._MEIPASS` and copying the *real* project
resources into a directory laid out exactly the way the `datas` tuples in
the spec would place them, then verifying the affected code still finds
them. This is the difference between "the path-construction logic looks
right" and "this actually would have worked in the shipped .exe" — the
migrations bug in particular would have meant *every* database operation
in a packaged build failed with "no such table" from the first launch
onward, and it was not caught by any existing test because every test
runs unfrozen.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from instacore_sync.db.database import Database, _migrations_dir
from instacore_sync.ui.theme.theme_manager import ThemeManager, _theme_dir

_PROJECT_SRC = Path(__file__).resolve().parents[2] / "src" / "instacore_sync"


def _fake_meipass_with_bundled_resources(tmp_path: Path) -> Path:
    """Lay out a fake sys._MEIPASS exactly the way pyinstaller.spec's
    `datas` tuples would: `(source_dir, "instacore_sync/db/migrations")`
    etc. means "place these files under <MEIPASS>/instacore_sync/db/migrations"."""
    meipass = tmp_path / "meipass"

    migrations_dst = meipass / "instacore_sync" / "db" / "migrations"
    shutil.copytree(_PROJECT_SRC / "db" / "migrations", migrations_dst)

    theme_dst = meipass / "instacore_sync" / "ui" / "theme"
    theme_dst.mkdir(parents=True)
    shutil.copy(_PROJECT_SRC / "ui" / "theme" / "dark_theme.qss", theme_dst)
    shutil.copy(_PROJECT_SRC / "ui" / "theme" / "light_theme.qss", theme_dst)

    return meipass


def test_database_migrations_are_found_and_applied_when_frozen(tmp_path: Path, monkeypatch) -> None:
    meipass = _fake_meipass_with_bundled_resources(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    # The precise regression assertion: resolution must point at the fake
    # MEIPASS, not the real source tree -- a revert to the old unconditional
    # `Path(__file__).parent` would still (incidentally) find the real
    # source-tree migrations under pytest, since pytest itself is never
    # actually frozen, so *only* asserting migrations were applied
    # wouldn't reliably catch that regression; asserting the resolved
    # directory itself would.
    assert _migrations_dir() == meipass / "instacore_sync" / "db" / "migrations"
    assert _migrations_dir() != _PROJECT_SRC / "db" / "migrations"

    db = Database(tmp_path / "frozen_test.db")
    with db.read_cursor() as cur:
        # If migrations silently found zero .sql files (the bug), this
        # table would never have been created and this raises
        # sqlite3.OperationalError: no such table: jobs.
        row = cur.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
    assert row["n"] == 0  # empty but the table exists -- that's the actual assertion

    with db.read_cursor() as cur:
        applied = {r["version"] for r in cur.execute("SELECT version FROM schema_migrations").fetchall()}
    assert applied == {1, 2, 3}  # every migration file actually got applied, not silently skipped


def test_theme_qss_is_found_and_loaded_when_frozen(tmp_path: Path, monkeypatch) -> None:
    meipass = _fake_meipass_with_bundled_resources(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert _theme_dir() == meipass / "instacore_sync" / "ui" / "theme"
    assert _theme_dir() != _PROJECT_SRC / "ui" / "theme"

    manager = ThemeManager()
    # If this resolved via the old Path(__file__).parent bug, this would
    # raise FileNotFoundError trying to read a path inside the PYZ
    # archive -- exactly what MainWindow.__init__ does unconditionally on
    # the very first window a packaged .exe ever shows.
    dark_qss = manager.stylesheet_for("dark")
    light_qss = manager.stylesheet_for("light")

    assert len(dark_qss) > 0
    assert len(light_qss) > 0
    assert dark_qss != light_qss

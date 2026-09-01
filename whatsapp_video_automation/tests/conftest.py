from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Qt-based tests (main window, wizard, health check, Safe Mode) construct
# real widgets to exercise real construction/wiring, not just view-model
# logic -- that needs *some* Qt platform plugin, and this test suite must
# run unattended in CI with no real display attached. Set before any Qt
# import happens, so `pytest -q` alone is sufficient; previously this
# required remembering to set QT_QPA_PLATFORM=offscreen by hand, which is
# exactly the kind of undocumented local-only requirement that makes a
# test suite pass on a developer's machine and fail (or silently not even
# run) in CI. A real display's QT_QPA_PLATFORM (if already set) is left
# alone.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_instacore_sync.db"


@pytest.fixture
def database(tmp_db_path: Path):
    from instacore_sync.db.database import Database

    db = Database(tmp_db_path)
    db.ensure_migrated()
    yield db
    db.close()


@pytest.fixture(autouse=True)
def _isolate_default_settings_path(tmp_path: Path, monkeypatch):
    """No test should ever read or write the *real* project's
    `config/settings.local.yaml` as a side effect of merely constructing
    a bare `AppSettings()` — many tests across this suite do exactly
    that, and `_YamlSettingsSource.__call__` seeds that file from
    `settings.example.yaml` the moment it doesn't already exist. In a
    fresh checkout (or this sandbox, repeatedly, since nothing here ever
    creates one for real) that means the *first* such test in a run
    silently writes a real file into the repository as a side effect of
    testing — CI should never mutate the checkout it's testing.
    Redirects every test's default settings path to an isolated
    `tmp_path` location by default; `_example_settings_path` (read-only,
    the real bundled template) is left alone so seeding still produces
    realistic defaults. Tests that specifically exercise path resolution
    itself (test_config.py, test_resource_paths.py) explicitly monkeypatch
    these again with their own target, which safely overrides this.
    """
    import instacore_sync.core.config as config_module

    monkeypatch.setattr(
        config_module, "_default_settings_path", lambda: tmp_path / "config" / "settings.local.yaml"
    )


@pytest.fixture(scope="session")
def qt_app():
    """A single shared `QApplication` for the whole test session — Qt
    only allows one per process, and constructing/tearing one down per
    test is unnecessary overhead and occasionally flaky. Individual tests
    are still isolated at the widget level (each constructs its own
    windows/widgets); only the underlying QApplication is shared."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app

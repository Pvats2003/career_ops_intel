"""Keeps the package version and pyproject.toml's declared version from
silently drifting apart — a real, if small, release-quality problem: a
built .exe whose Properties dialog, About text, and pip metadata each
claim a different version number is exactly the kind of thing that makes
a shipped app look unmaintained."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import instacore_sync

_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # tests/unit/test_version.py -> tests/unit -> tests -> root
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_valid_semver() -> None:
    assert _SEMVER_RE.match(instacore_sync.__version__), (
        f"__version__ = {instacore_sync.__version__!r} is not MAJOR.MINOR.PATCH"
    )


def test_version_matches_pyproject_toml() -> None:
    pyproject = _PROJECT_ROOT / "pyproject.toml"
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["project"]["version"] == instacore_sync.__version__

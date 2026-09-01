"""Unit tests for the frozen-vs-source-tree path resolution shared by
config.py (credentials/settings) and the application icon loader."""

from __future__ import annotations

import sys
from pathlib import Path

from instacore_sync.core import resource_paths


def test_is_frozen_reflects_sys_frozen(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert resource_paths.is_frozen() is True

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert resource_paths.is_frozen() is False


def test_app_base_dir_uses_executable_parent_when_frozen(tmp_path: Path, monkeypatch) -> None:
    fake_exe = tmp_path / "App" / "InstaCoreSync.exe"
    fake_exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    assert resource_paths.app_base_dir() == fake_exe.parent


def test_app_base_dir_uses_project_root_when_not_frozen(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    root = resource_paths.app_base_dir()
    assert (root / "pyproject.toml").exists()


def test_bundled_resource_dir_uses_meipass_when_frozen(tmp_path: Path, monkeypatch) -> None:
    meipass = tmp_path / "extracted"
    meipass.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert resource_paths.bundled_resource_dir() == meipass


def test_bundled_resource_dir_falls_back_to_app_base_dir_if_meipass_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """PyInstaller always sets _MEIPASS when actually frozen, but this
    keeps a defined, non-crashing fallback rather than raising AttributeError
    if that assumption is ever wrong."""
    fake_exe = tmp_path / "InstaCoreSync.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    assert resource_paths.bundled_resource_dir() == tmp_path


def test_icon_path_resolves_to_a_real_file_in_source_tree(monkeypatch) -> None:
    """Regression test for the icon actually existing and being wired up
    (packaging/generate_icon.py must have been run) — not just that the
    path-construction logic is self-consistent."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    path = resource_paths.icon_path()
    assert path.name == "app_icon.ico"
    assert path.exists(), "run packaging/generate_icon.py to (re)generate the app icon"


def test_icon_path_resolves_under_meipass_when_frozen(tmp_path: Path, monkeypatch) -> None:
    meipass = tmp_path / "extracted"
    icon_dir = meipass / "instacore_sync" / "ui" / "resources" / "icons"
    icon_dir.mkdir(parents=True)
    (icon_dir / "app_icon.ico").write_bytes(b"fake ico bytes")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert resource_paths.icon_path() == icon_dir / "app_icon.ico"

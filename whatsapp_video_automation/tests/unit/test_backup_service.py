"""Tests for full backup/restore (settings + database + logs).

The database round-trip test is the one that matters most: it writes a
real job through `JobsRepository` into a real (WAL-mode) `Database`,
backs it up while the source connection is still open (exactly what
happens when an automatic backup runs against the live app), restores
into a *different* location, and confirms the row is still there and
intact — proving the SQLite online-backup approach actually produces a
consistent, restorable snapshot rather than a torn WAL-mode file copy.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

from instacore_sync.db.database import Database
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.models import VideoJob
from instacore_sync.services.backup import backup_service as bs


def _paths(tmp_path: Path, suffix: str = "") -> bs.BackupPaths:
    return bs.BackupPaths(
        settings_file=tmp_path / f"settings{suffix}.local.yaml",
        database_file=tmp_path / f"instacore_sync{suffix}.db",
        logs_dir=tmp_path / f"logs{suffix}",
        backups_dir=tmp_path / f"backups{suffix}",
    )


def test_create_backup_bundles_settings_db_and_logs(tmp_path: Path, database: Database) -> None:
    # `database` fixture's underlying file lives at tmp_db_path, not under
    # tmp_path directly -- point the backup at it explicitly.
    paths = bs.BackupPaths(
        settings_file=tmp_path / "settings.local.yaml",
        database_file=database._db_path,
        logs_dir=tmp_path / "logs",
        backups_dir=tmp_path / "backups",
    )
    paths.settings_file.write_text("watch_folder: /tmp/watch\n", encoding="utf-8")
    paths.logs_dir.mkdir(parents=True)
    (paths.logs_dir / "instacore_sync.log").write_text('{"event": "test"}\n', encoding="utf-8")

    zip_path = bs.create_backup(paths)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "settings.local.yaml" in names
    assert "instacore_sync.db" in names
    assert "logs/instacore_sync.log" in names


def test_backup_and_restore_round_trips_a_real_job(tmp_path: Path, database: Database) -> None:
    jobs_repo = JobsRepository(database)
    job = VideoJob(source_path=Path("/tmp/IC-188_clip.mp4"), original_filename="IC-188_clip.mp4")
    job.device_id = "IC-188"
    jobs_repo.upsert(job)

    source_paths = bs.BackupPaths(
        settings_file=tmp_path / "settings.local.yaml",
        database_file=database._db_path,
        logs_dir=tmp_path / "logs",
        backups_dir=tmp_path / "backups",
    )
    source_paths.settings_file.write_text("watch_folder: /tmp/watch\n", encoding="utf-8")

    zip_path = bs.create_backup(source_paths)

    # Restore into a *separate* location -- simulates restoring onto a
    # fresh/different machine, and proves this doesn't depend on the
    # source database still existing.
    restore_root = tmp_path / "restored"
    restore_paths = bs.BackupPaths(
        settings_file=restore_root / "settings.local.yaml",
        database_file=restore_root / "instacore_sync.db",
        logs_dir=restore_root / "logs",
        backups_dir=restore_root / "backups",
    )

    bs.restore_backup(zip_path, restore_paths)

    assert restore_paths.settings_file.read_text(encoding="utf-8") == "watch_folder: /tmp/watch\n"

    restored_db = Database(restore_paths.database_file)
    restored_db.ensure_migrated()
    restored_repo = JobsRepository(restored_db)
    restored_job = restored_repo.get(job.job_id)
    assert restored_job is not None
    assert restored_job.device_id == "IC-188"
    assert restored_job.original_filename == "IC-188_clip.mp4"
    restored_db.close()


def test_restore_clears_stale_wal_sidecar_files(tmp_path: Path) -> None:
    """Regression guard: restoring a backup over an existing database
    must not let old -wal/-shm files from the *previous* database get
    replayed against the newly-restored one."""
    paths = _paths(tmp_path)
    paths.database_file.write_bytes(b"old db content")
    wal = paths.database_file.with_name(paths.database_file.name + "-wal")
    shm = paths.database_file.with_name(paths.database_file.name + "-shm")
    wal.write_bytes(b"stale wal data")
    shm.write_bytes(b"stale shm data")

    # Build a minimal valid backup zip containing just a database entry.
    backup_zip = tmp_path / "manual_backup.zip"
    with zipfile.ZipFile(backup_zip, "w") as zf:
        zf.writestr("instacore_sync.db", b"restored db content")

    bs.restore_backup(backup_zip, paths)

    assert paths.database_file.read_bytes() == b"restored db content"
    assert not wal.exists()
    assert not shm.exists()


def test_restore_raises_for_missing_archive(tmp_path: Path) -> None:
    import pytest

    from instacore_sync.core.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError):
        bs.restore_backup(tmp_path / "does_not_exist.zip", _paths(tmp_path))


def test_prune_old_backups_keeps_only_the_most_recent(tmp_path: Path) -> None:
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    paths = []
    for i in range(7):
        p = backups_dir / f"instacore_sync_backup_2026010{i}_000000.zip"
        p.write_bytes(b"x")
        paths.append(p)
        time.sleep(0.01)  # ensure distinct mtimes isn't required -- filenames already sort

    deleted = bs.prune_old_backups(backups_dir, keep=3)

    assert deleted == 4
    remaining = bs.list_backups(backups_dir)
    assert len(remaining) == 3
    # The 3 kept must be the lexicographically-latest (== most recent, given
    # the YYYYMMDD_HHMMSS naming scheme sorts chronologically).
    assert remaining == sorted(paths, reverse=True)[:3]


def test_list_backups_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert bs.list_backups(tmp_path / "does_not_exist") == []

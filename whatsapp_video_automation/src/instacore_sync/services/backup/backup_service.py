"""Full backup/restore: settings + database (which is also where the
"queue" — the `jobs` table — and every other piece of pipeline state
already lives, so backing up the DB backs up the queue too, there is no
separate queue file) + structured logs, bundled into one timestamped zip.

This is deliberately a *file-level* operation, not something layered on
top of `AppSettings.export_backup` (which only ever covered configuration
— folders, Drive/Sheets IDs, OCR/upload options — not data). Restoring
requires an app restart: this never tries to hot-swap the database out
from under a running pipeline.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from instacore_sync.core.exceptions import ConfigurationError
from instacore_sync.core.logging_setup import get_logger

logger = get_logger(__name__)

_SETTINGS_ARCNAME = "settings.local.yaml"
_DATABASE_ARCNAME = "instacore_sync.db"
_LOGS_ARCNAME_PREFIX = "logs/"
_BACKUP_FILENAME_PREFIX = "instacore_sync_backup_"


@dataclass(frozen=True, slots=True)
class BackupPaths:
    """Where the pieces of one backup come from / go to — passed in
    explicitly rather than re-derived from `AppSettings` internally, so
    this module has no dependency on the config layer and can be unit
    tested with plain tmp_path fixtures."""

    settings_file: Path
    database_file: Path
    logs_dir: Path
    backups_dir: Path


def create_backup(paths: BackupPaths) -> Path:
    """Creates `<backups_dir>/instacore_sync_backup_<timestamp>.zip`
    containing the current settings file, a consistent snapshot of the
    live database (via SQLite's own online backup API — safe to do while
    the app and its WAL-mode database are in active use, unlike a plain
    file copy which could grab a torn/inconsistent read), and every file
    under the logs directory. Returns the created zip's path.
    """
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = paths.backups_dir / f"{_BACKUP_FILENAME_PREFIX}{timestamp}.zip"

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db_snapshot = tmp_dir / _DATABASE_ARCNAME
        if paths.database_file.exists():
            _snapshot_database(paths.database_file, db_snapshot)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if paths.settings_file.exists():
                zf.write(paths.settings_file, arcname=_SETTINGS_ARCNAME)
            if db_snapshot.exists():
                zf.write(db_snapshot, arcname=_DATABASE_ARCNAME)
            if paths.logs_dir.exists():
                for log_file in sorted(paths.logs_dir.glob("*")):
                    if log_file.is_file():
                        zf.write(log_file, arcname=f"{_LOGS_ARCNAME_PREFIX}{log_file.name}")

    logger.info("backup.created", path=str(zip_path))
    return zip_path


def _snapshot_database(source: Path, destination: Path) -> None:
    """Uses SQLite's online backup API rather than a plain file copy:
    a WAL-mode database's on-disk `.db` file alone is not a consistent
    snapshot while writers are active (committed data can still be sitting
    in the `-wal` file) — `sqlite3.Connection.backup()` handles this
    correctly regardless of what's mid-flight.
    """
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(str(destination))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def restore_backup(archive_path: Path, paths: BackupPaths) -> None:
    """Extracts a backup zip over the current settings file, database,
    and logs directory. Overwrites in place — the caller is responsible
    for telling the user this requires restarting the app (this function
    doesn't stop/start anything; it just isn't safe to call while the
    pipeline holds the database open for writes).
    """
    if not archive_path.exists():
        raise ConfigurationError(f"Backup file not found: {archive_path}")

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = set(zf.namelist())

        if _SETTINGS_ARCNAME in names:
            paths.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(_SETTINGS_ARCNAME) as src, paths.settings_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)

        if _DATABASE_ARCNAME in names:
            paths.database_file.parent.mkdir(parents=True, exist_ok=True)
            # Drop any stale WAL/SHM sidecar files from the *current* database
            # before restoring -- otherwise SQLite would try to replay old
            # WAL frames against the newly-restored (unrelated) database file.
            for suffix in ("-wal", "-shm"):
                sidecar = paths.database_file.with_name(paths.database_file.name + suffix)
                sidecar.unlink(missing_ok=True)
            with zf.open(_DATABASE_ARCNAME) as src, paths.database_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)

        if paths.logs_dir is not None:
            paths.logs_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                if name.startswith(_LOGS_ARCNAME_PREFIX) and not name.endswith("/"):
                    target = paths.logs_dir / Path(name).name
                    with zf.open(name) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

    logger.info("backup.restored", path=str(archive_path))


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.exists():
        return []
    return sorted(backups_dir.glob(f"{_BACKUP_FILENAME_PREFIX}*.zip"), reverse=True)


def prune_old_backups(backups_dir: Path, *, keep: int = 5) -> int:
    """Deletes all but the `keep` most recent backups. Returns how many
    were deleted. Automatic backups run on every app start (see
    `app.py`); without pruning, a long-lived install would accumulate an
    unbounded number of DB snapshots on disk."""
    backups = list_backups(backups_dir)
    to_delete = backups[keep:]
    for path in to_delete:
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("backup.prune_failed", path=str(path), error=str(exc))
    return len(to_delete)

"""SQLite connection management.

Design notes:
  * WAL journal mode so the UI thread can read (dashboard polling, Logs view)
    while worker threads write (job status transitions) without blocking.
  * One connection per thread (SQLite connections are not thread-safe to
    share). `Database.connection()` returns a thread-local connection,
    lazily opened and migrated once per process.
  * A single `RLock` serializes writes to avoid "database is locked" errors
    under WAL when many upload workers finish around the same time; reads
    do not take the lock.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from instacore_sync.core.exceptions import RepositoryError
from instacore_sync.core.logging_setup import get_logger
from instacore_sync.core.resource_paths import bundled_resource_dir, is_frozen

logger = get_logger(__name__)


def _migrations_dir() -> Path:
    """Where the `*.sql` migration files live.

    Regression fix: this used to be `Path(__file__).parent / "migrations"`
    at module import time — correct from source, but silently catastrophic
    once frozen: a module bundled into the PYZ archive has no real
    on-disk `__file__`, so `_run_migrations()`'s glob would find zero
    `.sql` files, `schema_migrations` and every other table would never
    get created, and *every* database operation in a packaged .exe would
    fail with "no such table" from the first launch onward. Migrations
    are bundled as `datas` in `packaging/pyinstaller.spec`, resolved the
    same frozen-aware way as the theme QSS files and settings template.
    """
    if is_frozen():
        return bundled_resource_dir() / "instacore_sync" / "db" / "migrations"
    return Path(__file__).resolve().parent / "migrations"


class Database:
    """Owns the SQLite file, schema migrations, and per-thread connections."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._migrated = False
        self._migration_lock = threading.Lock()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_connection()
            self._local.conn = conn
        self.ensure_migrated()
        return conn

    def ensure_migrated(self) -> None:
        if self._migrated:
            return
        with self._migration_lock:
            if self._migrated:
                return
            self._run_migrations()
            self._migrated = True

    def _run_migrations(self) -> None:
        conn = getattr(self._local, "conn", None) or self._new_connection()
        self._local.conn = conn
        applied: set[int] = set()
        try:
            rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
            applied = {row["version"] for row in rows}
        except sqlite3.OperationalError:
            pass  # schema_migrations doesn't exist yet -> nothing applied.

        migration_files = sorted(_migrations_dir().glob("*.sql"))
        for path in migration_files:
            version = int(path.stem.split("_", 1)[0])
            if version in applied:
                continue
            logger.info("db.migration.apply", version=version, file=path.name)
            script = path.read_text(encoding="utf-8")
            with self._write_lock:
                try:
                    conn.executescript(script)
                    conn.commit()
                except sqlite3.Error as exc:
                    conn.rollback()
                    raise RepositoryError(f"Migration {path.name} failed: {exc}") from exc

    @contextmanager
    def write_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for a write transaction: serialized, auto commit/rollback."""
        conn = self.connection()
        with self._write_lock:
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def read_cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connection()
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

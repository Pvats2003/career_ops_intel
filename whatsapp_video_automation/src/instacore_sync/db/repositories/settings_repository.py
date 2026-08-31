"""Key/value store (`app_state`) and the Drive folder-id cache."""

from __future__ import annotations

from datetime import datetime

from instacore_sync.db.database import Database


class SettingsRepository:
    """Small persisted key/value pairs that don't belong in the YAML config
    (e.g. last authenticated Google account, last full-sync timestamp)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._db.read_cursor() as cur:
            row = cur.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self._db.write_cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, datetime.now().isoformat()),
            )


class DriveFolderCacheRepository:
    """Avoids a Drive `files.list` round trip for every video in the same folder."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, cache_key: str) -> str | None:
        with self._db.read_cursor() as cur:
            row = cur.execute(
                "SELECT folder_id FROM drive_folder_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return row["folder_id"] if row else None

    def set(self, cache_key: str, folder_id: str, parent_folder_id: str | None = None) -> None:
        with self._db.write_cursor() as cur:
            cur.execute(
                """
                INSERT INTO drive_folder_cache (cache_key, folder_id, parent_folder_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    folder_id = excluded.folder_id,
                    parent_folder_id = excluded.parent_folder_id
                """,
                (cache_key, folder_id, parent_folder_id, datetime.now().isoformat()),
            )

    def clear(self) -> None:
        with self._db.write_cursor() as cur:
            cur.execute("DELETE FROM drive_folder_cache")

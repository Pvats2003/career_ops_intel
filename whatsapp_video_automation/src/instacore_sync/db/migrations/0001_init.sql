-- InstaCore Sync — initial schema (migration 0001)
-- Applied automatically at startup by Database.initialize() (see database.py),
-- tracked in schema_migrations so it only ever runs once per DB file.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per video discovered by the folder watcher. This is the live
-- working table the pipeline reads/writes as a job moves through states;
-- `upload_logs` below is the durable audit trail written once a job settles.
CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    source_path         TEXT NOT NULL,
    original_filename   TEXT NOT NULL,
    status              TEXT NOT NULL,
    file_size_bytes     INTEGER NOT NULL DEFAULT 0,
    file_hash_sha256    TEXT,
    device_id           TEXT,
    ocr_confidence      REAL NOT NULL DEFAULT 0,
    ocr_engine_used     TEXT,
    drive_file_id       TEXT,
    drive_link          TEXT,
    drive_folder_id     TEXT,
    sheet_row_number    INTEGER,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    bytes_uploaded      INTEGER NOT NULL DEFAULT 0,
    upload_speed_bps    REAL NOT NULL DEFAULT 0,
    discovered_at       TEXT NOT NULL,
    started_at          TEXT,
    completed_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_device_id ON jobs(device_id);
CREATE INDEX IF NOT EXISTS idx_jobs_discovered_at ON jobs(discovered_at);

-- SHA-256 -> upload record, used to skip duplicate uploads even across app
-- restarts and even if the source file was renamed. `job_id` is informational
-- only (no FK to `jobs`): this table is a permanent, append-only dedup index
-- that must survive any future pruning of old rows from the `jobs` working
-- table, so it must never be constrained by that table's lifecycle.
CREATE TABLE IF NOT EXISTS uploaded_hashes (
    file_hash_sha256    TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL,
    original_filename   TEXT NOT NULL,
    drive_file_id       TEXT NOT NULL,
    drive_link          TEXT NOT NULL,
    uploaded_at         TEXT NOT NULL
);

-- Durable, append-only audit log. Every job that reaches a terminal state
-- (completed / failed / needs_review / duplicate) gets exactly one row here.
-- This is what the Logs view searches/filters/exports to CSV.
CREATE TABLE IF NOT EXISTS upload_logs (
    log_id              TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL,
    filename             TEXT NOT NULL,
    device_id           TEXT,
    status              TEXT NOT NULL,
    ocr_confidence      REAL NOT NULL DEFAULT 0,
    ocr_engine_used     TEXT,
    file_hash_sha256    TEXT,
    drive_link          TEXT,
    error_message       TEXT,
    created_at          TEXT NOT NULL,
    completed_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_status ON upload_logs(status);
CREATE INDEX IF NOT EXISTS idx_logs_device_id ON upload_logs(device_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON upload_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_filename ON upload_logs(filename);

-- Cache of "date folder name" -> Drive folder id, and "date/IC-xxx" -> Drive
-- folder id, so the pipeline doesn't re-list Drive for every single video.
CREATE TABLE IF NOT EXISTS drive_folder_cache (
    cache_key           TEXT PRIMARY KEY,   -- e.g. "31 Aug" or "31 Aug/IC-188"
    folder_id           TEXT NOT NULL,
    parent_folder_id    TEXT,
    created_at          TEXT NOT NULL
);

-- Lightweight key/value store for things that don't warrant a YAML round
-- trip (e.g. last-seen OAuth account email, last successful sheet sync).
CREATE TABLE IF NOT EXISTS app_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations (version) VALUES (1);

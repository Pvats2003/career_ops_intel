-- Adds per-stage timing and full-traceback fields to the durable audit log,
-- so the Logs screen can show/search/export OCR time, upload time, and
-- total processing time per video, and a stack trace is available for
-- truly unexpected failures without digging through the rotating
-- developer log file for a matching timestamp.

ALTER TABLE upload_logs ADD COLUMN ocr_duration_seconds REAL;
ALTER TABLE upload_logs ADD COLUMN upload_duration_seconds REAL;
ALTER TABLE upload_logs ADD COLUMN total_duration_seconds REAL;
ALTER TABLE upload_logs ADD COLUMN stack_trace TEXT;

INSERT OR IGNORE INTO schema_migrations (version) VALUES (3);

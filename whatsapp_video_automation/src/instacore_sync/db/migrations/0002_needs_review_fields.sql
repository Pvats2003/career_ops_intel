-- Adds fields needed by the Needs Review resolution screen:
--   * ocr_raw_text: the raw OCR text read from the frame that produced the
--     best (even if not confident enough) Device ID candidate, shown to the
--     operator so they can see *why* OCR was unsure.
--   * manually_confirmed: set when an operator picks a Device ID by hand on
--     the Needs Review screen, so VideoProcessor knows to trust it and skip
--     re-running OCR (which would otherwise immediately overwrite the
--     operator's choice with the same low-confidence guess that sent the
--     video to Needs Review in the first place).
--
-- A separate migration file (rather than editing 0001_init.sql) because a
-- migration that has already been applied to someone's local database must
-- never change out from under them — see docs/DATABASE_SCHEMA.md.

ALTER TABLE jobs ADD COLUMN ocr_raw_text TEXT;
ALTER TABLE jobs ADD COLUMN manually_confirmed INTEGER NOT NULL DEFAULT 0;

INSERT OR IGNORE INTO schema_migrations (version) VALUES (2);

"""App-wide constants that are not user-configurable."""

from __future__ import annotations

APP_NAME = "InstaCore Sync"
APP_ORG = "CareerOpsIntel"
APP_ID = "com.careeropsintel.instacoresync"

DEFAULT_DATA_DIR_NAME = "InstacoreSync"
DEFAULT_SETTINGS_FILENAME = "settings.local.yaml"
DEFAULT_DB_FILENAME = "instacore_sync.db"

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv"})

# Files WhatsApp Desktop writes to while a download/copy is still in flight.
INCOMPLETE_FILE_SUFFIXES = frozenset({".crdownload", ".part", ".tmp", ".download"})

# A file must not change size for this long before we consider it "settled"
# (WhatsApp Desktop streams videos to disk; we must not open a partial file).
FILE_STABILITY_WINDOW_SECONDS = 1.5
FILE_STABILITY_POLL_SECONDS = 0.25
FILE_STABILITY_MAX_WAIT_SECONDS = 60.0

DEVICE_ID_REGEX_DEFAULT = r"IC-\d{1,5}"

GOOGLE_DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)

# Drive API upload resumable chunk boundaries must be multiples of 256 KiB.
DRIVE_CHUNK_ALIGNMENT_BYTES = 256 * 1024

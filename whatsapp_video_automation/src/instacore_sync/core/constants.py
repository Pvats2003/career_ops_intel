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

# Bounded on both sides: a bare `IC-\d+` search (no boundary) false-positive
# matches any noisy OCR text ending in "...IC-<digits>" — e.g. "MAGIC-188" or
# "GENERIC-23" both contain a literal "IC-188"/"IC-23" substring. The
# lookbehind/lookahead require the match to be a standalone token, not part
# of a longer word or a longer number.
DEVICE_ID_REGEX_DEFAULT = r"(?<![A-Za-z0-9])IC-\d{1,5}(?!\d)"

GOOGLE_DRIVE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)

# Drive API upload resumable chunk boundaries must be multiples of 256 KiB.
DRIVE_CHUNK_ALIGNMENT_BYTES = 256 * 1024

# Hard ceiling on frames examined during the last-resort full-video OCR scan.
# Without this, a video that's chronically hard to read (bad lighting, an
# unusual UI skin) combined with a long recording could otherwise spend
# minutes of CPU scanning every 0.5s of a 10+ minute video before finally
# giving up and routing to Needs Review — at 150-500 videos/day even a
# handful of such videos would stall the whole queue. Capped at 120 frames
# (60s of coverage at the default 0.5s sampling interval), which comfortably
# covers where a Device ID banner would realistically still be on-screen.
OCR_FULL_SCAN_MAX_FRAMES = 120

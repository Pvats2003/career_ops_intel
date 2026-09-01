"""Filesystem helpers shared by the watcher and pipeline."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from instacore_sync.core.constants import (
    FILE_STABILITY_MAX_WAIT_SECONDS,
    FILE_STABILITY_POLL_SECONDS,
    FILE_STABILITY_WINDOW_SECONDS,
    INCOMPLETE_FILE_SUFFIXES,
    VIDEO_EXTENSIONS,
)
from instacore_sync.core.exceptions import FileNotStableError


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_incomplete_download(path: Path) -> bool:
    return path.suffix.lower() in INCOMPLETE_FILE_SUFFIXES


def wait_until_stable(
    path: Path,
    *,
    window_seconds: float = FILE_STABILITY_WINDOW_SECONDS,
    poll_seconds: float = FILE_STABILITY_POLL_SECONDS,
    max_wait_seconds: float = FILE_STABILITY_MAX_WAIT_SECONDS,
) -> int:
    """Block until `path`'s size stops changing for `window_seconds`.

    WhatsApp Desktop writes videos to disk incrementally; opening the file
    too early yields a truncated/corrupt read. Returns the final, stable
    size in bytes. Raises `FileNotStableError` if the file never settles
    (or disappears) within `max_wait_seconds`.
    """
    deadline = time.monotonic() + max_wait_seconds
    last_size = -1
    stable_since: float | None = None

    while time.monotonic() < deadline:
        if not path.exists():
            raise FileNotStableError(f"File disappeared while waiting for it to stabilize: {path}")

        size = path.stat().st_size
        now = time.monotonic()

        if size != last_size:
            last_size = size
            stable_since = now
        elif stable_since is not None and (now - stable_since) >= window_seconds:
            return size

        time.sleep(poll_seconds)

    raise FileNotStableError(f"File never stabilized within {max_wait_seconds}s: {path}")


def move_to_folder(source: Path, destination_folder: Path) -> Path:
    destination_folder.mkdir(parents=True, exist_ok=True)
    destination = destination_folder / source.name
    destination = _dedupe_destination_name(destination)
    shutil.move(str(source), str(destination))
    return destination


def _dedupe_destination_name(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    counter = 1
    while True:
        candidate = destination.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1

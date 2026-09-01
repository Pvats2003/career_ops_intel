"""Filesystem helpers shared by the watcher and pipeline."""

from __future__ import annotations

import contextlib
import errno
import os
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


def move_to_folder(source: Path, destination_folder: Path, *, forced_name: str | None = None) -> Path:
    """Move `source` into `destination_folder`, choosing a unique name if
    one already exists there. `forced_name` overrides the base name to
    move under (defaults to `source.name`) — used by tests to simulate
    several different source files that all need to dedupe against the
    same target name, exactly as WhatsApp's repeating auto-naming does in
    production.

    Several videos can be routed to the same destination folder (Processed
    / NeedsReview / Failed) concurrently by different upload workers, and
    WhatsApp's own auto-naming convention (`VID-YYYYMMDD-WA000N.mp4`)
    genuinely repeats across different chats/senders on the same day — so
    two workers can legitimately need to dedupe against the *same* target
    name at the *same* time. A "check `.exists()`, then move" approach has
    a TOCTOU gap there: both workers can see the name is free and both
    move into it, with the loser's file silently overwriting the winner's.

    Instead, the destination name is *reserved* with `os.O_CREAT |
    O_EXCL` — an atomic, kernel-level "create only if it doesn't exist"
    that can never race, unlike a Python-level exists-then-write check —
    before anything is moved. If the reservation fails because the name
    is taken, the next numbered variant is tried the same way.
    """
    destination_folder.mkdir(parents=True, exist_ok=True)
    base_name = forced_name if forced_name is not None else source.name
    stem, suffix = Path(base_name).stem, Path(base_name).suffix
    counter = 0
    while True:
        name = base_name if counter == 0 else f"{stem} ({counter}){suffix}"
        candidate = destination_folder / name
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            counter += 1
            continue
        os.close(fd)
        break

    try:
        try:
            os.replace(str(source), str(candidate))
        except OSError as exc:
            if exc.errno != errno.EXDEV:  # not a cross-filesystem move
                raise
            shutil.copy2(str(source), str(candidate))
            os.remove(str(source))
    except Exception:
        # The reservation placeholder must not linger as a fake
        # "already processed" file if the actual transfer failed.
        with contextlib.suppress(OSError):
            os.remove(str(candidate))
        raise

    return candidate

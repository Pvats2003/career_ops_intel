"""Watches the WhatsApp download folder for newly arrived videos.

Uses `watchdog` for OS-level filesystem events (instant on Windows via
ReadDirectoryChangesW) plus a periodic full-directory reconciliation pass,
so a video is never missed even if an event is dropped (which does happen
under watchdog on network drives or during bursts of ~150-200 files/day).

Discovered paths are handed to a callback on a dedicated worker thread —
the callback is expected to block (it waits for the file to stabilize),
so we never do that work on watchdog's own event thread.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from instacore_sync.core.logging_setup import get_logger
from instacore_sync.domain.enums import WatcherStatus
from instacore_sync.utils.file_utils import is_incomplete_download, is_video_file

logger = get_logger(__name__)

DiscoveryCallback = Callable[[Path], None]


class _VideoEventHandler(FileSystemEventHandler):
    def __init__(self, on_candidate: Callable[[Path], None]) -> None:
        self._on_candidate = on_candidate

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_candidate(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._on_candidate(Path(event.dest_path))


class FolderWatcher:
    """Watches `folder` for new video files and reports each one exactly once."""

    def __init__(self, folder: Path, on_video_discovered: DiscoveryCallback) -> None:
        self._folder = folder
        self._callback = on_video_discovered
        self._observer: Observer | None = None
        self._status = WatcherStatus.STOPPED
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()
        self._candidate_queue: queue.Queue[Path] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._reconcile_thread: threading.Thread | None = None
        self._reconcile_interval_seconds = 15.0

    @property
    def status(self) -> WatcherStatus:
        return self._status

    def start(self) -> None:
        if self._status == WatcherStatus.RUNNING:
            return
        self._status = WatcherStatus.STARTING
        self._folder.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()

        # Seed `_seen` with everything already present so we don't reprocess
        # a backlog of already-handled videos on every app restart.
        with self._seen_lock:
            self._seen = {str(p) for p in self._folder.iterdir() if p.is_file()}

        self._observer = Observer()
        self._observer.schedule(_VideoEventHandler(self._enqueue), str(self._folder), recursive=False)

        try:
            self._observer.start()
        except OSError as exc:
            logger.error("watcher.start_failed", folder=str(self._folder), error=str(exc))
            self._status = WatcherStatus.ERROR
            raise

        self._worker_thread = threading.Thread(
            target=self._process_queue, name="folder-watcher-worker", daemon=True
        )
        self._worker_thread.start()

        self._reconcile_thread = threading.Thread(
            target=self._reconcile_loop, name="folder-watcher-reconcile", daemon=True
        )
        self._reconcile_thread.start()

        self._status = WatcherStatus.RUNNING
        logger.info("watcher.started", folder=str(self._folder))

    def stop(self) -> None:
        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
        self._candidate_queue.put_nowait(None)  # type: ignore[arg-type]
        self._status = WatcherStatus.STOPPED
        logger.info("watcher.stopped", folder=str(self._folder))

    def _enqueue(self, path: Path) -> None:
        if not is_video_file(path) or is_incomplete_download(path):
            return
        key = str(path)
        with self._seen_lock:
            if key in self._seen:
                return
            self._seen.add(key)
        self._candidate_queue.put(path)

    def _process_queue(self) -> None:
        while not self._stop_event.is_set():
            path = self._candidate_queue.get()
            if path is None:
                break
            try:
                self._callback(path)
            except Exception:  # noqa: BLE001 - never let one bad file kill the watcher
                logger.exception("watcher.callback_failed", path=str(path))

    def _reconcile_loop(self) -> None:
        while not self._stop_event.wait(self._reconcile_interval_seconds):
            try:
                if not self._folder.exists():
                    continue
                for path in self._folder.iterdir():
                    if path.is_file():
                        self._enqueue(path)
            except OSError as exc:
                logger.warning("watcher.reconcile_failed", error=str(exc))

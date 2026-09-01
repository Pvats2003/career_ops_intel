"""Regression test for the `_seen` unbounded-memory-growth fix.

`_seen` must not grow forever across a long-running session: once a video
has been moved out of the watch folder (the normal end state for every job,
per `VideoProcessor`), its entry should be pruned so `_seen`'s size tracks
"files currently sitting in the watch folder", not "every file ever seen
since the app started".
"""

from __future__ import annotations

from pathlib import Path

from instacore_sync.services.watcher.folder_watcher import FolderWatcher


def test_prune_seen_drops_entries_for_files_that_no_longer_exist(tmp_path: Path) -> None:
    watcher = FolderWatcher(tmp_path, on_video_discovered=lambda _p: None)

    still_present = tmp_path / "still_here.mp4"
    still_present.write_bytes(b"x")
    moved_away = tmp_path / "already_processed.mp4"  # never actually created

    watcher._seen = {str(still_present), str(moved_away)}

    watcher._prune_seen()

    assert watcher._seen == {str(still_present)}


def test_prune_seen_is_a_noop_when_all_files_present(tmp_path: Path) -> None:
    watcher = FolderWatcher(tmp_path, on_video_discovered=lambda _p: None)
    present = tmp_path / "a.mp4"
    present.write_bytes(b"x")
    watcher._seen = {str(present)}

    watcher._prune_seen()

    assert watcher._seen == {str(present)}


def test_enqueue_deduplicates_same_path_until_pruned(tmp_path: Path) -> None:
    discovered: list[Path] = []
    watcher = FolderWatcher(tmp_path, on_video_discovered=discovered.append)

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")

    watcher._enqueue(video)
    watcher._enqueue(video)  # second event for the same still-present file

    assert watcher._candidate_queue.qsize() == 1  # only enqueued once

    video.unlink()  # simulate VideoProcessor having moved it away
    watcher._prune_seen()
    watcher._enqueue(video)  # a hypothetical new file reusing the same name

    assert watcher._candidate_queue.qsize() == 2  # now allowed to be seen again

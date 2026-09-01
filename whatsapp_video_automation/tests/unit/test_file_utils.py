from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from instacore_sync.core.exceptions import FileNotStableError
from instacore_sync.utils.file_utils import (
    is_incomplete_download,
    is_video_file,
    move_to_folder,
    wait_until_stable,
)


@pytest.mark.parametrize(
    "name,expected",
    [("clip.mp4", True), ("clip.MOV", True), ("clip.txt", False), ("clip.mp4.crdownload", False)],
)
def test_is_video_file(name: str, expected: bool) -> None:
    assert is_video_file(Path(name)) is expected


def test_is_incomplete_download() -> None:
    assert is_incomplete_download(Path("video.mp4.crdownload")) is True
    assert is_incomplete_download(Path("video.mp4")) is False


def test_wait_until_stable_returns_final_size_once_writes_stop(tmp_path: Path) -> None:
    file_path = tmp_path / "growing.mp4"
    file_path.write_bytes(b"a" * 10)

    def _grow_then_stop() -> None:
        time.sleep(0.1)
        file_path.write_bytes(b"a" * 100)

    thread = threading.Thread(target=_grow_then_stop)
    thread.start()

    size = wait_until_stable(file_path, window_seconds=0.3, poll_seconds=0.05, max_wait_seconds=5.0)
    thread.join()

    assert size == 100


def test_wait_until_stable_raises_if_file_disappears(tmp_path: Path) -> None:
    file_path = tmp_path / "ghost.mp4"
    file_path.write_bytes(b"data")

    def _delete_soon() -> None:
        time.sleep(0.05)
        file_path.unlink()

    thread = threading.Thread(target=_delete_soon)
    thread.start()
    with pytest.raises(FileNotStableError):
        wait_until_stable(file_path, window_seconds=1.0, poll_seconds=0.02, max_wait_seconds=1.0)
    thread.join()


def test_move_to_folder_dedupes_name_collision(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    dest_dir = tmp_path / "dest"
    source_dir.mkdir()
    dest_dir.mkdir()

    existing = dest_dir / "clip.mp4"
    existing.write_bytes(b"already here")

    source_file = source_dir / "clip.mp4"
    source_file.write_bytes(b"new content")

    moved = move_to_folder(source_file, dest_dir)

    assert moved.name == "clip (1).mp4"
    assert moved.read_bytes() == b"new content"
    assert existing.read_bytes() == b"already here"


def test_move_to_folder_never_loses_a_file_under_concurrent_same_name_collisions(tmp_path: Path) -> None:
    """WhatsApp's own auto-naming convention repeats often (different
    chats/senders, same day), so several upload workers can legitimately
    try to move different videos with the *same* name into the same
    destination folder at the *same* time. A check-then-move approach has
    a TOCTOU gap here: two threads can both see a candidate name is free
    and both move into it, silently losing whichever moved second. Every
    one of N concurrently-moved same-named files must survive, each under
    its own distinct final name, with its own distinct content intact."""
    source_dir = tmp_path / "source"
    dest_dir = tmp_path / "dest"
    source_dir.mkdir()
    dest_dir.mkdir()

    n = 12
    sources = []
    for i in range(n):
        f = source_dir / f"src_{i}.mp4"  # distinct source names...
        f.write_bytes(f"content-{i}".encode())
        sources.append(f)

    def _move(source: Path) -> Path:
        # ...but every worker moves it under the SAME destination name,
        # exactly like several different videos named identically by
        # WhatsApp all landing in Needs Review/Processed together.
        return move_to_folder(source, dest_dir, forced_name="clip.mp4")

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(_move, sources))

    assert len(set(results)) == n, f"two workers collided on the same destination path: {results}"
    contents = {p.read_bytes() for p in results}
    assert contents == {f"content-{i}".encode() for i in range(n)}, "a file's content was lost/overwritten"

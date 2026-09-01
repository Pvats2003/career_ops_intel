from __future__ import annotations

import hashlib
from pathlib import Path

from instacore_sync.services.hashing.hash_service import HashService


def test_sha256_of_file_matches_hashlib(tmp_path: Path) -> None:
    content = b"instacore sync test payload" * 1000
    file_path = tmp_path / "sample.mp4"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    actual = HashService().sha256_of_file(file_path)

    assert actual == expected


def test_sha256_is_stable_across_chunk_boundaries(tmp_path: Path) -> None:
    # Larger than the service's internal 4 MiB chunk size, to make sure
    # streaming reads don't silently drop/duplicate bytes at the boundary.
    content = bytes(i % 256 for i in range(5 * 1024 * 1024))
    file_path = tmp_path / "large.mp4"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    actual = HashService().sha256_of_file(file_path)

    assert actual == expected


def test_different_content_produces_different_hash(tmp_path: Path) -> None:
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"content-a")
    b.write_bytes(b"content-b")

    service = HashService()
    assert service.sha256_of_file(a) != service.sha256_of_file(b)

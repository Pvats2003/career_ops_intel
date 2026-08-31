from __future__ import annotations

from pathlib import Path

from instacore_sync.db.database import Database
from instacore_sync.db.repositories.hashes_repository import HashesRepository
from instacore_sync.services.dedup.dedup_service import DedupService
from instacore_sync.services.hashing.hash_service import HashService


def _make_service(database: Database) -> DedupService:
    return DedupService(HashService(), HashesRepository(database))


def test_find_duplicate_returns_none_for_unknown_hash(database: Database) -> None:
    service = _make_service(database)
    assert service.find_duplicate("deadbeef" * 8) is None


def test_record_upload_then_find_duplicate_returns_record(database: Database, tmp_path: Path) -> None:
    service = _make_service(database)
    video = tmp_path / "IC-188_video.mp4"
    video.write_bytes(b"fake video bytes")

    file_hash = service.compute_hash(video)
    service.record_upload(file_hash, "job-1", "IC-188_video.mp4", "drive-file-1", "https://drive/1")

    duplicate = service.find_duplicate(file_hash)
    assert duplicate is not None
    assert duplicate.original_filename == "IC-188_video.mp4"
    assert duplicate.drive_file_id == "drive-file-1"


def test_recording_same_hash_twice_is_idempotent(database: Database, tmp_path: Path) -> None:
    service = _make_service(database)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"identical content")
    file_hash = service.compute_hash(video)

    service.record_upload(file_hash, "job-1", "clip.mp4", "drive-1", "link-1")
    service.record_upload(file_hash, "job-2", "clip_renamed.mp4", "drive-2", "link-2")

    duplicate = service.find_duplicate(file_hash)
    assert duplicate is not None
    assert duplicate.job_id == "job-1"  # first write wins; ON CONFLICT DO NOTHING

from __future__ import annotations

from pathlib import Path

from instacore_sync.db.database import Database
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob


def _job(name: str = "IC-188.mp4", status: JobStatus = JobStatus.DISCOVERED) -> VideoJob:
    return VideoJob(source_path=Path(f"/tmp/{name}"), original_filename=name, status=status)


def test_upsert_and_get_roundtrip(database: Database) -> None:
    repo = JobsRepository(database)
    job = _job()

    repo.upsert(job)
    fetched = repo.get(job.job_id)

    assert fetched is not None
    assert fetched.job_id == job.job_id
    assert fetched.original_filename == "IC-188.mp4"
    assert fetched.status == JobStatus.DISCOVERED


def test_upsert_updates_existing_row(database: Database) -> None:
    repo = JobsRepository(database)
    job = _job()
    repo.upsert(job)

    job.status = JobStatus.COMPLETED
    job.device_id = "IC-188"
    repo.upsert(job)

    fetched = repo.get(job.job_id)
    assert fetched is not None
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.device_id == "IC-188"
    # Still exactly one row for this job_id, not a duplicate insert.
    assert len(repo.list_by_status(JobStatus.COMPLETED)) == 1


def test_list_by_status_filters_correctly(database: Database) -> None:
    repo = JobsRepository(database)
    repo.upsert(_job("a.mp4", JobStatus.QUEUED))
    repo.upsert(_job("b.mp4", JobStatus.FAILED))
    repo.upsert(_job("c.mp4", JobStatus.QUEUED))

    queued = repo.list_by_status(JobStatus.QUEUED)
    assert {j.original_filename for j in queued} == {"a.mp4", "c.mp4"}


def test_list_active_excludes_terminal_statuses(database: Database) -> None:
    repo = JobsRepository(database)
    repo.upsert(_job("active.mp4", JobStatus.UPLOADING))
    repo.upsert(_job("done.mp4", JobStatus.COMPLETED))
    repo.upsert(_job("dead.mp4", JobStatus.FAILED))

    active = repo.list_active()
    assert {j.original_filename for j in active} == {"active.mp4"}


def test_counts_by_status(database: Database) -> None:
    repo = JobsRepository(database)
    repo.upsert(_job("a.mp4", JobStatus.QUEUED))
    repo.upsert(_job("b.mp4", JobStatus.QUEUED))
    repo.upsert(_job("c.mp4", JobStatus.FAILED))

    counts = repo.counts_by_status()
    assert counts[JobStatus.QUEUED] == 2
    assert counts[JobStatus.FAILED] == 1


def test_find_by_hash(database: Database) -> None:
    repo = JobsRepository(database)
    job = _job()
    job.file_hash_sha256 = "abc123"
    repo.upsert(job)

    found = repo.find_by_hash("abc123")
    assert found is not None
    assert found.job_id == job.job_id
    assert repo.find_by_hash("does-not-exist") is None

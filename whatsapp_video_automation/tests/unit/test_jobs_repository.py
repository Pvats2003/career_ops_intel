from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from instacore_sync.db.database import Database
from instacore_sync.db.repositories.jobs_repository import JobsRepository
from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob


def _job(
    name: str = "IC-188.mp4",
    status: JobStatus = JobStatus.DISCOVERED,
    discovered_at: datetime | None = None,
) -> VideoJob:
    return VideoJob(
        source_path=Path(f"/tmp/{name}"),
        original_filename=name,
        status=status,
        discovered_at=discovered_at or datetime.now(),
    )


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


def test_prune_terminal_jobs_older_than_deletes_old_completed_and_duplicate(database: Database) -> None:
    repo = JobsRepository(database)
    old = datetime.now() - timedelta(days=60)
    recent = datetime.now() - timedelta(hours=1)

    repo.upsert(_job("old_completed.mp4", JobStatus.COMPLETED, discovered_at=old))
    repo.upsert(_job("old_duplicate.mp4", JobStatus.DUPLICATE, discovered_at=old))
    repo.upsert(_job("recent_completed.mp4", JobStatus.COMPLETED, discovered_at=recent))

    deleted = repo.prune_terminal_jobs_older_than(datetime.now() - timedelta(days=30))

    assert deleted == 2
    remaining = {j.original_filename for j in repo.list_by_status(JobStatus.COMPLETED, JobStatus.DUPLICATE)}
    assert remaining == {"recent_completed.mp4"}


def test_prune_terminal_jobs_never_deletes_failed_or_needs_review(database: Database) -> None:
    """FAILED/NEEDS_REVIEW rows need a human to act on them — pruning must
    never make them silently disappear, no matter how old."""
    repo = JobsRepository(database)
    ancient = datetime.now() - timedelta(days=365)
    repo.upsert(_job("old_failed.mp4", JobStatus.FAILED, discovered_at=ancient))
    repo.upsert(_job("old_review.mp4", JobStatus.NEEDS_REVIEW, discovered_at=ancient))

    deleted = repo.prune_terminal_jobs_older_than(datetime.now() - timedelta(days=30))

    assert deleted == 0
    statuses = {j.original_filename for j in repo.list_by_status(JobStatus.FAILED, JobStatus.NEEDS_REVIEW)}
    assert statuses == {"old_failed.mp4", "old_review.mp4"}


def test_find_by_hash(database: Database) -> None:
    repo = JobsRepository(database)
    job = _job()
    job.file_hash_sha256 = "abc123"
    repo.upsert(job)

    found = repo.find_by_hash("abc123")
    assert found is not None
    assert found.job_id == job.job_id
    assert repo.find_by_hash("does-not-exist") is None

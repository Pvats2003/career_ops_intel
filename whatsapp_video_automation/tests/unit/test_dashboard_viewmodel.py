"""Regression test: `DashboardViewModel._jobs_by_id` must not grow without
bound. A terminal job (COMPLETED/FAILED/NEEDS_REVIEW/DUPLICATE) is never
looked up again — retaining it would leak memory for the lifetime of the
process on a long-running install processing 150-500 videos/day."""

from __future__ import annotations

from pathlib import Path

from instacore_sync.domain.enums import JobStatus
from instacore_sync.domain.models import VideoJob
from instacore_sync.ui.viewmodels.dashboard_viewmodel import DashboardViewModel
from instacore_sync.workers.signals import PipelineSignalBus


def _job(status: JobStatus) -> VideoJob:
    return VideoJob(source_path=Path("clip.mp4"), original_filename="clip.mp4", status=status)


def test_terminal_jobs_are_dropped_not_cached_forever(qt_app) -> None:  # noqa: ANN001
    bus = PipelineSignalBus()
    vm = DashboardViewModel(bus)

    active = _job(JobStatus.UPLOADING)
    bus.job_updated.emit(active)
    assert active.job_id in vm._jobs_by_id

    for status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.NEEDS_REVIEW, JobStatus.DUPLICATE):
        job = _job(status)
        bus.job_updated.emit(job)
        assert job.job_id not in vm._jobs_by_id, f"{status} job was retained instead of dropped"

    # The still-active job must be unaffected by other jobs reaching terminal states.
    assert active.job_id in vm._jobs_by_id


def test_many_completed_jobs_do_not_accumulate(qt_app) -> None:  # noqa: ANN001
    bus = PipelineSignalBus()
    vm = DashboardViewModel(bus)

    for _ in range(500):
        bus.job_updated.emit(_job(JobStatus.COMPLETED))

    assert len(vm._jobs_by_id) == 0

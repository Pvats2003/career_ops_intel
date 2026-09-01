from __future__ import annotations

from pathlib import Path

import pytest

from instacore_sync.domain.models import VideoJob
from instacore_sync.services.upload.upload_queue import UploadQueue


@pytest.mark.asyncio
async def test_put_and_get_preserves_fifo_order() -> None:
    queue = UploadQueue()
    job_a = VideoJob(source_path=Path("a.mp4"), original_filename="a.mp4")
    job_b = VideoJob(source_path=Path("b.mp4"), original_filename="b.mp4")

    await queue.put(job_a)
    await queue.put(job_b)

    assert await queue.get() is job_a
    assert await queue.get() is job_b


@pytest.mark.asyncio
async def test_waiting_count_reflects_queue_depth() -> None:
    queue = UploadQueue()
    assert queue.waiting_count == 0

    queue.put_nowait(VideoJob(source_path=Path("a.mp4"), original_filename="a.mp4"))
    queue.put_nowait(VideoJob(source_path=Path("b.mp4"), original_filename="b.mp4"))
    assert queue.waiting_count == 2

    await queue.get()
    assert queue.waiting_count == 1

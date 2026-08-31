"""Thin, typed wrapper around `asyncio.Queue[VideoJob]`.

Exists mainly so the rest of the codebase depends on a small, purpose-named
type (`UploadQueue`) instead of a bare generic `asyncio.Queue`, and so queue
depth is trivially observable for the dashboard's "Videos waiting" stat.
"""

from __future__ import annotations

import asyncio

from instacore_sync.domain.models import VideoJob


class UploadQueue:
    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[VideoJob] = asyncio.Queue(maxsize=maxsize)

    async def put(self, job: VideoJob) -> None:
        await self._queue.put(job)

    def put_nowait(self, job: VideoJob) -> None:
        self._queue.put_nowait(job)

    async def get(self) -> VideoJob:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    @property
    def waiting_count(self) -> int:
        return self._queue.qsize()

    async def join(self) -> None:
        await self._queue.join()

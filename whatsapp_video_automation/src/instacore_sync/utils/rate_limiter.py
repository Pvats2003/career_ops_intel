"""A simple thread-safe semaphore-based concurrency limiter.

Used to cap simultaneous Drive uploads (10-20 concurrent, per the product
spec) independently of however many jobs the pipeline has queued.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = threading.Semaphore(max(1, max_concurrent))
        self._lock = threading.Lock()
        self._active = 0

    @contextmanager
    def slot(self) -> Iterator[None]:
        self._semaphore.acquire()
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

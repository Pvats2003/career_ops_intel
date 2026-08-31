"""Shared retry policies (built on tenacity) used by Drive/Sheets/upload code.

Centralizing this means every network call in the app retries with the same
exponential-backoff-plus-jitter shape, configured from `UploadSettings`,
instead of each service reinventing its own loop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")


def network_retry(
    *,
    max_attempts: int = 5,
    base_backoff_seconds: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """A tenacity decorator factory for transient network/API failures."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=base_backoff_seconds, max=60.0),
        retry=retry_if_exception_type(retry_on),
    )

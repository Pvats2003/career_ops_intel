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
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from instacore_sync.utils.google_api_errors import is_transient_google_api_error

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


def google_api_retry(
    *,
    max_attempts: int = 5,
    base_backoff_seconds: float = 2.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Like `network_retry`, but only retries `HttpError`s classified as
    transient (rate limiting, backend/server errors) — see
    `google_api_errors.py`. A permission-denied or not-found error fails
    fast instead of burning up to a minute of backoff for nothing.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=base_backoff_seconds, max=60.0),
        retry=retry_if_exception(is_transient_google_api_error),
    )

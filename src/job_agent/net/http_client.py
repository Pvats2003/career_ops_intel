"""A small resilient HTTP client: timeouts, retries, exponential backoff
with jitter, and a hard retry cap — BUILD PROMPT sections 26 and 33.

This is deliberately not a generic "retry everything" client: 4xx errors
(except 429) are client/request errors that a retry cannot fix and are
raised immediately, since retrying a malformed request just wastes the
source's rate-limit budget for no benefit.
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx


class TransientHTTPError(Exception):
    """Raised for a 429 or 5xx response — safe to retry."""

    def __init__(self, status_code: int, url: str, retry_after: float | None = None):
        self.status_code = status_code
        self.url = url
        self.retry_after = retry_after
        super().__init__(f"transient HTTP {status_code} from {url}")


class ResilientHttpClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 5.0,
        backoff_multiplier: float = 2.0,
        backoff_max_seconds: float = 300.0,
        timeout: float = 15.0,
        sleep_fn: Any = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self.max_retries = max(1, max_retries)
        self.backoff_seconds = backoff_seconds
        self.backoff_multiplier = backoff_multiplier
        self.backoff_max_seconds = backoff_max_seconds
        self._sleep = sleep_fn

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        delay = self.backoff_seconds
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = self._parse_retry_after(response)
                    last_exc = TransientHTTPError(response.status_code, url, retry_after)
                else:
                    response.raise_for_status()
                    return response.json()

            if attempt == self.max_retries:
                break

            wait = last_exc.retry_after if isinstance(last_exc, TransientHTTPError) else None
            if wait is None:
                jitter = random.uniform(0, delay * 0.25)
                wait = min(delay + jitter, self.backoff_max_seconds)
            self._sleep(wait)
            delay = min(delay * self.backoff_multiplier, self.backoff_max_seconds)

        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if header is None:
            return None
        try:
            return float(header)
        except ValueError:
            return None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ResilientHttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

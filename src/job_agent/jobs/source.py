"""JobSource plugin interface — BUILD PROMPT section 6.

Adding a new job source means implementing this interface; the discovery
pipeline (`job_agent.jobs.service`) and everything downstream (dedup,
freshness, matching) is written against `JobSource`/`Job` and never against
a specific adapter, so new sources plug in without touching core code
(section 46).

Every adapter is expected to:
  * use an official API / structured feed where one exists (never scrape
    when an API is available),
  * respect the source's own rate limits (via `ResilientHttpClient`, not
    ad-hoc `requests.get` calls),
  * never attempt to bypass CAPTCHA, login walls, or bot detection — if a
    source requires that, it does not get a `JobSource` implementation,
    it gets a `notes:` entry in config/sources.yaml explaining why.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from job_agent.jobs.schema import Job

RawPosting = dict[str, Any]


@dataclass(frozen=True)
class HealthCheckResult:
    healthy: bool
    detail: str
    checked_at: datetime


class JobSource(ABC):
    """Base class for a job discovery adapter."""

    name: str

    @abstractmethod
    def search(self) -> list[RawPosting]:
        """Return the current raw postings from this source.

        Implementations should return source-specific dicts as-is (no
        normalization here) — `raw_data` on the final `Job` must be able to
        reconstruct exactly what came back from the source (section 7).
        """

    def fetch_job(self, raw: RawPosting) -> RawPosting:
        """Fetch full detail for one posting, if `search()` returns summaries
        only. Default: passthrough — most job-board list APIs already
        return full content and don't need a second request per job (this
        also keeps request volume low per section 40's cost-optimization
        pipeline)."""
        return raw

    @abstractmethod
    def normalize(self, raw: RawPosting) -> Job:
        """Convert one raw posting into the canonical Job schema."""

    @abstractmethod
    def get_posted_time(self, raw: RawPosting) -> datetime | None:
        """Extract a verifiable posting timestamp, or None.

        Returning None is correct and expected when the source doesn't
        expose a reliable posted-date — freshness classification then
        reports UNKNOWN_POST_DATE rather than a guess.
        """

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        """Confirm the source is reachable and returning sane data."""

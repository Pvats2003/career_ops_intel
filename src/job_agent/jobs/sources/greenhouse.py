"""Greenhouse Job Board API adapter.

Uses the public, unauthenticated, read-only Job Board API
(`https://boards-api.greenhouse.io/v1/boards/{token}/jobs`) that Greenhouse
itself publishes for exactly this purpose — no ToS concern, no bot
detection to respect or bypass, no login wall. See
https://developers.greenhouse.io/job-board.html.

Greenhouse does not expose a true "originally posted" timestamp on this
endpoint; `updated_at` is the closest verifiable signal, so `get_posted_time`
uses it but callers should treat it as "last updated", not "first posted" —
we do not overstate what the source actually tells us.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.source import HealthCheckResult, JobSource, RawPosting
from job_agent.jobs.sources._html import html_to_text
from job_agent.logging.setup import redact_text
from job_agent.net.http_client import ResilientHttpClient

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseJobSource(JobSource):
    name = "greenhouse"

    def __init__(self, board_token: str, company_name: str, http: ResilientHttpClient) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._http = http

    def _jobs_url(self) -> str:
        return f"{BASE_URL}/{self.board_token}/jobs"

    def search(self) -> list[RawPosting]:
        data = self._http.get_json(self._jobs_url(), params={"content": "true"})
        jobs = data.get("jobs", [])
        if not isinstance(jobs, list):
            raise ValueError(
                f"greenhouse[{self.board_token}]: expected 'jobs' to be a list, "
                f"got {type(jobs).__name__} — the API response shape may have changed"
            )
        return jobs

    def normalize(self, raw: RawPosting) -> Job:
        location_name = (raw.get("location") or {}).get("name")
        description = html_to_text(raw.get("content"))
        remote_type = RemoteType.UNKNOWN
        if location_name and "remote" in location_name.lower():
            remote_type = RemoteType.REMOTE

        return Job(
            source=self.name,
            source_job_id=str(raw["id"]),
            company=self.company_name,
            title=raw["title"],
            description=description,
            location=location_name,
            locations=(location_name,) if location_name else (),
            remote_type=remote_type,
            application_url=raw["absolute_url"],
            posted_at=self.get_posted_time(raw),
            raw_data=raw,
        )

    def get_posted_time(self, raw: RawPosting) -> datetime | None:
        updated_at = raw.get("updated_at")
        if not updated_at:
            return None
        try:
            dt = datetime.fromisoformat(updated_at)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    def health_check(self) -> HealthCheckResult:
        """`detail` is scrubbed with `redact_text()` before being returned
        — no caller currently displays/logs a health check's `detail`
        (this endpoint takes no credential today, so there is nothing to
        leak in practice), but the boundary is closed here rather than
        wherever a future caller happens to consume it, matching the
        centralized-redaction pattern the rest of the codebase uses."""
        checked_at = datetime.now(UTC)
        try:
            data: Any = self._http.get_json(self._jobs_url(), params={"content": "false"})
        except Exception as exc:  # noqa: BLE001
            return HealthCheckResult(
                healthy=False, detail=redact_text(str(exc)), checked_at=checked_at
            )
        if not isinstance(data, dict) or "jobs" not in data:
            return HealthCheckResult(
                healthy=False,
                detail="response did not contain a 'jobs' key",
                checked_at=checked_at,
            )
        return HealthCheckResult(
            healthy=True, detail=f"{len(data['jobs'])} jobs listed", checked_at=checked_at
        )

"""Lever Postings API adapter.

Uses Lever's public, unauthenticated, read-only Postings API
(`https://api.lever.co/v0/postings/{company}?mode=json`), published by Lever
for external consumption — no ToS concern, no auth, nothing to bypass. See
https://github.com/lever/postings-api.

Unlike Greenhouse, Lever's `createdAt` is an actual posting-creation
timestamp (epoch milliseconds), so `get_posted_time` here is a genuine
"posted at" signal rather than a last-updated proxy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.source import HealthCheckResult, JobSource, RawPosting
from job_agent.jobs.sources._html import html_to_text
from job_agent.logging.setup import redact_text
from job_agent.net.http_client import ResilientHttpClient

BASE_URL = "https://api.lever.co/v0/postings"


class LeverJobSource(JobSource):
    name = "lever"

    def __init__(self, company_slug: str, company_name: str, http: ResilientHttpClient) -> None:
        self.company_slug = company_slug
        self.company_name = company_name
        self._http = http

    def _postings_url(self) -> str:
        return f"{BASE_URL}/{self.company_slug}"

    def search(self) -> list[RawPosting]:
        data = self._http.get_json(self._postings_url(), params={"mode": "json"})
        if not isinstance(data, list):
            raise ValueError(
                f"lever[{self.company_slug}]: expected a JSON list of postings, "
                f"got {type(data).__name__} — the API response shape may have changed"
            )
        return data

    def normalize(self, raw: RawPosting) -> Job:
        categories = raw.get("categories") or {}
        location = categories.get("location")
        commitment = categories.get("commitment")

        description_parts = [html_to_text(raw.get("description"))]
        for section in raw.get("lists") or []:
            section_text = html_to_text(section.get("content"))
            if section_text:
                heading = section.get("text") or ""
                description_parts.append(f"{heading}\n{section_text}" if heading else section_text)
        description = "\n\n".join(p for p in description_parts if p) or None

        remote_type = RemoteType.UNKNOWN
        if location and "remote" in location.lower():
            remote_type = RemoteType.REMOTE

        return Job(
            source=self.name,
            source_job_id=str(raw["id"]),
            company=self.company_name,
            title=raw["text"],
            description=description,
            location=location,
            locations=(location,) if location else (),
            remote_type=remote_type,
            employment_type=commitment,
            application_url=raw.get("hostedUrl") or raw.get("applyUrl", ""),
            posted_at=self.get_posted_time(raw),
            raw_data=raw,
        )

    def get_posted_time(self, raw: RawPosting) -> datetime | None:
        created_at = raw.get("createdAt")
        if created_at is None:
            return None
        try:
            return datetime.fromtimestamp(int(created_at) / 1000, tz=UTC)
        except (ValueError, TypeError, OverflowError):
            return None

    def health_check(self) -> HealthCheckResult:
        """`detail` is scrubbed with `redact_text()` before being returned
        — see `GreenhouseJobSource.health_check()` for why this boundary
        is closed here rather than left to a future caller."""
        checked_at = datetime.now(UTC)
        try:
            data: Any = self._http.get_json(self._postings_url(), params={"mode": "json"})
        except Exception as exc:  # noqa: BLE001
            return HealthCheckResult(
                healthy=False, detail=redact_text(str(exc)), checked_at=checked_at
            )
        if not isinstance(data, list):
            return HealthCheckResult(
                healthy=False, detail="response was not a JSON list", checked_at=checked_at
            )
        return HealthCheckResult(
            healthy=True, detail=f"{len(data)} postings listed", checked_at=checked_at
        )

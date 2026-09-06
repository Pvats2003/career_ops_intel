"""Arbeitnow Job Board API adapter.

Uses Arbeitnow's public, unauthenticated, read-only API
(`https://www.arbeitnow.com/api/job-board-api`), published for exactly
this kind of consumption — no ToS concern, no key required. See
https://documenter.getpostman.com/view/18545278/UVJbJdKh.

No search-term/query parameter exists on this API — it returns every
current listing, paginated — so unlike Remotive/Adzuna, exactly ONE
instance of this adapter covers the whole source; `job_agent.jobs.
service.build_sources` never creates more than one. `max_pages` bounds
total requests per scan regardless of how many listings the source holds.

Arbeitnow explicitly reports `visa_sponsorship` (a real boolean per
listing) — the one source in this codebase that can state visa
sponsorship as a verified fact rather than "Unknown"; every other source
leaves `Job.visa_information` unset, and `job_agent.matching`/the web
layer must keep treating an unset value as genuinely unknown, never as
"no sponsorship" (BUILD PROMPT section 6's "never assume visa
sponsorship" rule).

NOTE: this sandbox's network policy blocks outbound calls to
arbeitnow.com (same restriction already documented for Greenhouse/Lever
in config/sources.yaml), so this adapter could not be live-verified from
here. Confirm connectivity before enabling in a real deployment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.source import HealthCheckResult, JobSource, RawPosting
from job_agent.jobs.sources._html import html_to_text
from job_agent.logging.setup import redact_text
from job_agent.net.http_client import ResilientHttpClient

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowJobSource(JobSource):
    name = "arbeitnow"

    def __init__(self, http: ResilientHttpClient, *, max_pages: int = 3) -> None:
        self.max_pages = max_pages
        self._http = http

    def search(self) -> list[RawPosting]:
        postings: list[RawPosting] = []
        page = 1
        while page <= self.max_pages:
            data = self._http.get_json(BASE_URL, params={"page": page})
            if not isinstance(data, dict) or "data" not in data:
                raise ValueError(
                    "arbeitnow: expected a dict with a 'data' key, "
                    f"got {type(data).__name__} — the API response shape may have changed"
                )
            page_postings = data["data"]
            if not isinstance(page_postings, list):
                raise ValueError(
                    f"arbeitnow: expected 'data' to be a list, got {type(page_postings).__name__}"
                )
            postings.extend(page_postings)
            if not page_postings or not (data.get("links") or {}).get("next"):
                break
            page += 1
        return postings

    def normalize(self, raw: RawPosting) -> Job:
        location = raw.get("location")
        remote = bool(raw.get("remote"))
        tags = raw.get("tags") or []
        job_types = raw.get("job_types") or []

        visa_sponsorship = raw.get("visa_sponsorship")
        visa_information = None
        if visa_sponsorship is True:
            visa_information = "Visa sponsorship offered (per source posting)"
        elif visa_sponsorship is False:
            visa_information = "No visa sponsorship (per source posting)"
        # visa_sponsorship is None/missing -> visa_information stays None
        # (unknown), never inferred as "no sponsorship".

        return Job(
            source=self.name,
            source_job_id=str(raw.get("slug") or raw["url"]),
            company=raw.get("company_name") or "Unknown",
            title=raw["title"],
            description=html_to_text(raw.get("description")),
            location=location,
            locations=(location,) if location else (),
            remote_type=RemoteType.REMOTE if remote else RemoteType.UNKNOWN,
            employment_type=", ".join(job_types) if job_types else None,
            visa_information=visa_information,
            application_url=raw["url"],
            posted_at=self.get_posted_time(raw),
            raw_data={**raw, "tags": tags},
        )

    def get_posted_time(self, raw: RawPosting) -> datetime | None:
        created_at = raw.get("created_at")
        if created_at is None:
            return None
        try:
            return datetime.fromtimestamp(int(created_at), tz=UTC)
        except (ValueError, TypeError, OverflowError, OSError):
            return None

    def health_check(self) -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        try:
            data: Any = self._http.get_json(BASE_URL, params={"page": 1})
        except Exception as exc:  # noqa: BLE001
            return HealthCheckResult(
                healthy=False, detail=redact_text(str(exc)), checked_at=checked_at
            )
        if not isinstance(data, dict) or "data" not in data:
            return HealthCheckResult(
                healthy=False, detail="response did not contain a 'data' key",
                checked_at=checked_at,
            )
        return HealthCheckResult(
            healthy=True, detail=f"{len(data['data'])} jobs on page 1", checked_at=checked_at
        )

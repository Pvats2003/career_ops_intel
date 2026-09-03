"""Remotive Remote Jobs API adapter.

Uses Remotive's public, unauthenticated, read-only API
(`https://remotive.com/api/remote-jobs`), published for exactly this kind
of consumption — no ToS concern, no key required, no bot detection to
respect or bypass. See https://remotive.com/remote-jobs/api.

One instance covers ONE search term (the `search` query param) —
`job_agent.jobs.service.build_sources` creates one instance per query
drawn from the candidate's generated search portfolio (`job_agent.jobs.
query_generator`), capped by `config/sources.yaml`'s `max_queries` for
this source, so the number of real requests stays bounded regardless of
how large the candidate's query portfolio grows.

Every listing here is remote by construction (Remotive only lists remote
roles) and worldwide by nature — this is one of the sources that gives
"remote"/"worldwide" real, non-fabricated content per BUILD PROMPT
section 2, without requiring any credential from the candidate.

NOTE: this sandbox's network policy blocks outbound calls to remotive.com
(same restriction already documented for Greenhouse/Lever in config/
sources.yaml), so this adapter could not be live-verified from here.
Confirm connectivity before enabling in a real deployment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.source import HealthCheckResult, JobSource, RawPosting
from job_agent.jobs.sources._html import html_to_text
from job_agent.logging.setup import redact_text
from job_agent.net.http_client import ResilientHttpClient

BASE_URL = "https://remotive.com/api/remote-jobs"


class RemotiveJobSource(JobSource):
    name = "remotive"

    def __init__(self, search_term: str, http: ResilientHttpClient, *, limit: int = 50) -> None:
        # Named `search_term`, never `search` — this class also defines a
        # `search()` METHOD (the JobSource ABC contract), and an instance
        # attribute of that same name would shadow it, breaking every call
        # to `self.search()`.
        self.search_term = search_term
        self.limit = limit
        self._http = http

    def _query_params(self) -> dict[str, Any]:
        return {"search": self.search_term, "limit": self.limit}

    def search(self) -> list[RawPosting]:
        data = self._http.get_json(BASE_URL, params=self._query_params())
        jobs = data.get("jobs", [])
        if not isinstance(jobs, list):
            raise ValueError(
                f"remotive[{self.search_term!r}]: expected 'jobs' to be a list, "
                f"got {type(jobs).__name__} — the API response shape may have changed"
            )
        return jobs

    def normalize(self, raw: RawPosting) -> Job:
        location = raw.get("candidate_required_location")
        return Job(
            source=self.name,
            source_job_id=str(raw["id"]),
            company=raw.get("company_name") or "Unknown",
            title=raw["title"],
            description=html_to_text(raw.get("description")),
            location=location,
            locations=(location,) if location else (),
            remote_type=RemoteType.REMOTE,
            employment_type=raw.get("job_type"),
            # Remotive's `salary` field is free text (e.g. "$60k - $80k"),
            # not a structured min/max/currency triple — never parsed into
            # a guessed number here; it stays out of raw_data-derived
            # fields entirely rather than being misrepresented as exact.
            application_url=raw["url"],
            posted_at=self.get_posted_time(raw),
            raw_data=raw,
        )

    def get_posted_time(self, raw: RawPosting) -> datetime | None:
        published = raw.get("publication_date")
        if not published:
            return None
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    def health_check(self) -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        try:
            data: Any = self._http.get_json(
                BASE_URL, params={"search": self.search_term, "limit": 1}
            )
        except Exception as exc:  # noqa: BLE001
            return HealthCheckResult(
                healthy=False, detail=redact_text(str(exc)), checked_at=checked_at
            )
        if not isinstance(data, dict) or "jobs" not in data:
            return HealthCheckResult(
                healthy=False, detail="response did not contain a 'jobs' key",
                checked_at=checked_at,
            )
        return HealthCheckResult(
            healthy=True,
            detail=f"{len(data['jobs'])} jobs listed for search={self.search_term!r}",
            checked_at=checked_at,
        )

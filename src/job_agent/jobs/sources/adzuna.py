"""Adzuna Jobs API adapter.

Uses Adzuna's official public Jobs API
(`https://api.adzuna.com/v1/api/jobs/{country}/search/{page}`) — requires
a free `app_id`/`app_key` pair from https://developer.adzuna.com/, passed
as query parameters per Adzuna's own documented auth scheme (never a
bypass of anything). See https://developer.adzuna.com/docs/search.

This is the one source in this codebase that gives real, structured
multi-country coverage (BUILD PROMPT section 2's country list) — Adzuna
publishes per-country endpoints for, among others: gb (UK), us, ca, in,
sg, au, de, nl — covering most of the requested countries directly.
Ireland and UAE are not Adzuna markets as of this writing; there is no
adapter for them here rather than a fabricated one.

One instance covers ONE (country, search term) pair — `job_agent.jobs.
service.build_sources` creates one instance per configured country in
`config/sources.yaml`'s `countries:` list, crossed with up to `max_queries`
terms from the candidate's generated search portfolio, so total request
volume is `len(countries) * max_queries` per scan, bounded by both knobs.

NOTE: this sandbox's network policy blocks outbound calls to
api.adzuna.com (same restriction already documented for Greenhouse/Lever
in config/sources.yaml), so this adapter could not be live-verified from
here. Confirm connectivity — and a real app_id/app_key — before enabling
in a real deployment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from job_agent.jobs.schema import Job, RemoteType
from job_agent.jobs.source import HealthCheckResult, JobSource, RawPosting
from job_agent.logging.setup import redact_text
from job_agent.net.http_client import ResilientHttpClient

BASE_URL = "https://api.adzuna.com/v1/api/jobs"


class AdzunaJobSource(JobSource):
    name = "adzuna"

    def __init__(
        self,
        country: str,
        search_term: str,
        app_id: str,
        app_key: str,
        http: ResilientHttpClient,
        *,
        results_per_page: int = 20,
    ) -> None:
        self.country = country
        self.search_term = search_term
        self._app_id = app_id
        self._app_key = app_key
        self.results_per_page = results_per_page
        self._http = http

    def _search_url(self) -> str:
        return f"{BASE_URL}/{self.country}/search/1"

    def _query_params(self) -> dict[str, Any]:
        return {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "what": self.search_term,
            "results_per_page": self.results_per_page,
            "content-type": "application/json",
        }

    def search(self) -> list[RawPosting]:
        data = self._http.get_json(self._search_url(), params=self._query_params())
        results = data.get("results", [])
        if not isinstance(results, list):
            raise ValueError(
                f"adzuna[{self.country}/{self.search_term!r}]: expected 'results' to be a "
                f"list, got {type(results).__name__} — the API response shape may have changed"
            )
        return results

    def normalize(self, raw: RawPosting) -> Job:
        location = (raw.get("location") or {}).get("display_name")
        category = (raw.get("category") or {}).get("label")
        return Job(
            source=self.name,
            source_job_id=str(raw["id"]),
            company=(raw.get("company") or {}).get("display_name") or "Unknown",
            title=raw["title"],
            description=raw.get("description"),
            location=location,
            locations=(location,) if location else (),
            remote_type=RemoteType.UNKNOWN,
            employment_type=raw.get("contract_time") or raw.get("contract_type"),
            salary_min=raw.get("salary_min"),
            salary_max=raw.get("salary_max"),
            # Adzuna's amounts are always in the target country's local
            # currency but the API does not echo a currency code per
            # listing — never guessed here; left unset rather than
            # assuming e.g. USD for a non-US country search.
            application_url=raw["redirect_url"],
            posted_at=self.get_posted_time(raw),
            raw_data={**raw, "_query_category": category},
        )

    def get_posted_time(self, raw: RawPosting) -> datetime | None:
        created = raw.get("created")
        if not created:
            return None
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    def health_check(self) -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        try:
            data: Any = self._http.get_json(
                self._search_url(), params={**self._query_params(), "results_per_page": 1}
            )
        except Exception as exc:  # noqa: BLE001
            return HealthCheckResult(
                healthy=False, detail=redact_text(str(exc)), checked_at=checked_at
            )
        if not isinstance(data, dict) or "results" not in data:
            return HealthCheckResult(
                healthy=False, detail="response did not contain a 'results' key",
                checked_at=checked_at,
            )
        return HealthCheckResult(
            healthy=True,
            detail=f"{len(data['results'])} results for {self.country}/{self.search_term!r}",
            checked_at=checked_at,
        )

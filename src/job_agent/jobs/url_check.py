"""Live application-URL reachability check — the one part of application
viability (Part 3.9's "URL works") that actually costs a network request,
so it is deliberately NOT computed automatically for every job on every
page load. It is triggered on demand (one job at a time) from the job
detail view, and the result is always honest about what it actually
observed: REACHABLE / UNREACHABLE / UNKNOWN (timeout, DNS failure, or any
other error that doesn't tell us the URL is actually broken) — never
upgraded to a false "works"/"broken" claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

from job_agent.db.models import utcnow

URLCheckStatus = Literal["REACHABLE", "UNREACHABLE", "UNKNOWN"]


@dataclass(frozen=True)
class URLCheckResult:
    status: URLCheckStatus
    detail: str
    checked_at: datetime


def check_application_url(
    url: str, *, timeout: float = 6.0, transport: httpx.BaseTransport | None = None
) -> URLCheckResult:
    """`transport` is exposed only so tests can substitute an
    `httpx.MockTransport` instead of making a real request — production
    callers never pass it, so every real check goes out over the network."""
    checked_at = utcnow()
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "CareerOS/1.0"},
            transport=transport,
        ) as client:
            response = client.head(url)
            if response.status_code == 405:
                response = client.get(url)
    except httpx.TimeoutException:
        return URLCheckResult("UNKNOWN", "Request timed out", checked_at)
    except httpx.TransportError as exc:
        return URLCheckResult("UNKNOWN", f"Could not connect: {exc}", checked_at)

    if response.status_code < 400:
        return URLCheckResult("REACHABLE", f"HTTP {response.status_code}", checked_at)
    return URLCheckResult("UNREACHABLE", f"HTTP {response.status_code}", checked_at)

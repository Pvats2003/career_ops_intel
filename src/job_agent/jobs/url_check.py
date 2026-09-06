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

import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx

from job_agent.db.models import utcnow

URLCheckStatus = Literal["REACHABLE", "UNREACHABLE", "UNKNOWN"]

_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class URLCheckResult:
    status: URLCheckStatus
    detail: str
    checked_at: datetime


def _is_unsafe_target(url: str) -> str | None:
    """`application_url` on a job comes from an external source (an ATS
    API, a job board) that this system does not control — a malicious or
    compromised source could set it to an internal address (cloud
    metadata service, localhost, a private-network admin panel) to turn
    this on-demand check into server-side request forgery. Returns a
    human-readable reason the URL is unsafe to fetch, or None if it looks
    like an ordinary public web address. IP literals are checked without
    touching the network; hostnames are resolved via DNS so the resolved
    address — not just the string — is what actually gets validated."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"Unsupported URL scheme: {parts.scheme or '(none)'}"
    hostname = parts.hostname
    if not hostname:
        return "URL has no hostname"

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        return f"Could not resolve hostname: {exc}"

    for _family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return f"Resolves to a non-public address ({ip})"
    return None


def check_application_url(
    url: str, *, timeout: float = 6.0, transport: httpx.BaseTransport | None = None
) -> URLCheckResult:
    """`transport` is exposed only so tests can substitute an
    `httpx.MockTransport` instead of making a real request — production
    callers never pass it, so every real check goes out over the network.
    The SSRF guard (`_is_unsafe_target`) only applies when `transport` is
    None: a mock transport never opens a real socket, so there is nothing
    for it to protect, and it lets tests use non-resolving hostnames
    freely; every real network call is always checked.

    Redirects are followed manually (rather than via httpx's
    `follow_redirects=True`) so each hop is re-validated against
    `_is_unsafe_target` before it's fetched — a safe first URL that
    redirects to an internal address is refused, not silently followed."""
    checked_at = utcnow()
    current_url = url
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "CareerOS/1.0"},
            transport=transport,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                if transport is None:
                    unsafe_reason = _is_unsafe_target(current_url)
                    if unsafe_reason is not None:
                        return URLCheckResult("UNKNOWN", unsafe_reason, checked_at)

                response = client.head(current_url)
                if response.status_code == 405:
                    response = client.get(current_url)

                if response.is_redirect:
                    next_url = response.headers.get("location")
                    if not next_url:
                        break
                    current_url = str(httpx.URL(current_url).join(next_url))
                    continue
                break
            else:
                return URLCheckResult("UNKNOWN", "Too many redirects", checked_at)
    except httpx.TimeoutException:
        return URLCheckResult("UNKNOWN", "Request timed out", checked_at)
    except httpx.TransportError as exc:
        return URLCheckResult("UNKNOWN", f"Could not connect: {exc}", checked_at)

    if response.status_code < 400:
        return URLCheckResult("REACHABLE", f"HTTP {response.status_code}", checked_at)
    return URLCheckResult("UNREACHABLE", f"HTTP {response.status_code}", checked_at)

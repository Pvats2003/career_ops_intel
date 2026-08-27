"""Phase 6C — narrow, POST-only HTTP client for real submission attempts.

This is deliberately NOT a general-purpose HTTP client. It is bound, at
construction, to exactly one destination URL — there is no method on this
class, anywhere, that accepts a URL as an argument. A caller cannot make
this client POST anywhere except the single endpoint it was built for; a
`RealStructuredATSProvider` (or any future real provider) that wants to
submit to a different posting must construct a new client for that
posting's own, separately-approved URL, never redirect an existing one.

This is also NOT `job_agent.net.http_client.ResilientHttpClient`. That
client is for read-only, idempotent GET requests during job discovery,
where retrying a failed attempt is always safe — at worst it re-reads data
that was never mutated. A POST that attempts a real application submission
is never safe to retry blindly: if the request reached the platform before
the failure occurred, retrying risks a duplicate real-world submission.
`SubmissionHttpClient.post()` therefore makes exactly ONE attempt per call
and never retries internally, regardless of which kind of failure occurs.

THE CENTRAL SAFETY DISTINCTION: not every network failure means the same
thing.

  - A failure while still trying to CONNECT (DNS resolution, TCP connect,
    waiting for a pooled connection, or a timeout during that stage) means
    no request bytes were ever written to the wire — the platform never
    saw anything. That is a `ProviderTimeoutError` (connect-stage timeout)
    or a plain `ProviderError` (connect refused/DNS failure): ordinary,
    unambiguous failures, exactly like any other provider timeout.
  - ANY failure after that point — while writing the request body, while
    waiting for a response, a dropped connection while reading one, a
    malformed/incomplete response, or any other httpx error this client
    does not specifically recognize as pre-connect — is treated as
    `SubmissionOutcomeUnknownError`. The request may have already reached
    the platform. This client does not guess toward the safer-looking
    "must have failed" interpretation; per
    `job_agent.applications.errors.SubmissionOutcomeUnknownError`'s own
    docstring, an ambiguous outcome must never be treated as a plain,
    retryable failure.
  - An actual HTTP response — ANY status code, including 4xx/5xx — means
    the round trip completed: the platform received the request and sent
    back a real answer. That is not ambiguous at the network level, so it
    is returned to the caller as a `SubmissionHttpResponse` rather than
    raised as an error. Deciding what a given status code/body MEANS (a
    genuine success, a rejection, a platform-side error worth treating as
    uncertain) is the calling provider's job, not this client's — this
    client only reports the transport-level fact that a response arrived
    and what it contained. See this module's docstring boundary note in
    `job_agent.applications.provider`: a provider reports facts, the core
    decides consequences, and this client is one more fact-reporting layer
    underneath the provider, not a decision-maker itself.

No credential handling lives here. A caller that needs to authenticate
passes already-resolved header values into `post()` (typically obtained
from a `job_agent.security.credentials.CredentialProvider` immediately
before the call) — this client never reads an environment variable, a
config file, or any credential source itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from job_agent.applications.errors import (
    ProviderError,
    ProviderTimeoutError,
    SubmissionOutcomeUnknownError,
)

# Failures at or before the connect stage: no request bytes were ever sent.
# Deliberately a short, explicit allowlist rather than "everything not
# otherwise recognized" — see this module's docstring on why the default
# for an unrecognized failure must lean toward ambiguous, not safe.
_CONNECT_STAGE_TIMEOUTS: tuple[type[Exception], ...] = (
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)
_CONNECT_STAGE_ERRORS: tuple[type[Exception], ...] = (httpx.ConnectError,)


@dataclass(frozen=True)
class SubmissionHttpResponse:
    """The transport-level facts of a completed round trip. Says nothing
    about whether the submission succeeded — only that a response arrived,
    with this status code, body, and headers. Interpretation belongs to
    the calling provider."""

    status_code: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)


class SubmissionHttpClient:
    """POST-only HTTP client bound at construction to exactly one URL.

    There is no `url` parameter anywhere on `post()` — this is the
    structural guarantee, not just a convention: a caller cannot make an
    instance POST anywhere other than the URL it was built with, no
    matter what arguments it passes.
    """

    def __init__(
        self,
        target_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._target_url = target_url
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def target_url(self) -> str:
        return self._target_url

    def post(
        self,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> SubmissionHttpResponse:
        """Make exactly one POST attempt to this client's bound URL. Never
        retries internally — see this module's docstring for why a POST
        must not be retried blindly by this layer."""
        try:
            response = self._client.post(self._target_url, json=payload, headers=headers)
        except _CONNECT_STAGE_TIMEOUTS as exc:
            raise ProviderTimeoutError(
                f"Timed out connecting to submission endpoint before any request "
                f"data was sent: {exc}"
            ) from exc
        except _CONNECT_STAGE_ERRORS as exc:
            raise ProviderError(
                f"Could not connect to submission endpoint; no request data was "
                f"sent: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SubmissionOutcomeUnknownError(
                "A network failure occurred after the submission request may "
                f"already have been sent; the outcome cannot be determined: {exc}"
            ) from exc
        return SubmissionHttpResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SubmissionHttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

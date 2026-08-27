class ProviderError(Exception):
    """Base class for any ApplicationProvider failure (timeout, unexpected
    platform response, etc). Callers must treat this the same way
    `job_agent.jobs.service` treats a source failure — log it, don't crash
    the whole batch, never fabricate a result to paper over it."""


class ProviderTimeoutError(ProviderError):
    """The provider could not complete an operation in time."""


class SubmissionRefusedError(ProviderError):
    """The provider will not attempt a submission.

    This is the expected, everyday outcome in Phase 5: no real ATS
    integration exists yet, so the shipped `ManualReviewProvider` always
    raises this from `submit()`. It is not a bug — it is the mechanism
    that makes real external submission structurally impossible until a
    real, reviewed provider is built and explicitly wired in.
    """


class VerificationFailedError(ProviderError):
    """Raised when verification cannot produce trustworthy evidence.

    Distinct from "verified=False" (a normal, expected `VerificationResult`
    for "we checked and it wasn't confirmed") — this is for the provider
    itself being unable to even attempt verification (e.g. transport error).
    """


class SubmissionOutcomeUnknownError(ProviderError):
    """Raised when a real submission attempt's outcome cannot be determined
    — specifically, when the request may have already reached the
    platform before the failure occurred (a network timeout or connection
    reset *while waiting for the response*, as opposed to a connection
    failure *before* the request was ever sent).

    This is deliberately a DIFFERENT exception from `ProviderTimeoutError`
    (which covers ordinary timeouts — e.g. during discovery/inspection —
    where nothing ambiguous happened) and from a plain `ProviderError`/
    `SubmissionRefusedError` (which mean "definitely did not submit,
    safe to retry"). `job_agent.applications.service.submit_application`
    catches this specifically, before its generic `ProviderError` handler,
    and routes it to `ApplicationStatus.SUBMISSION_UNCERTAIN` — never to
    `FAILED` (which `retry_application()` can resurrect back to `MATCHED`
    and re-attempt) and never to `SUBMITTED` (which would claim success
    with no evidence). A provider that cannot tell "definitely not sent"
    apart from "possibly sent" for a given failure MUST raise this, not
    guess toward either safer-looking alternative.
    """

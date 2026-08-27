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

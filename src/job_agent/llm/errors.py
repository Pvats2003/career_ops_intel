class LLMUnavailableError(Exception):
    """No LLM provider is configured/reachable (e.g. no API key set).

    This is not a failure to be retried — callers should fall back to
    deterministic-only behavior, per BUILD PROMPT section 40's
    cost-optimization guidance (don't call an LLM you can't reach) and
    section 36's safe-by-default posture (missing config degrades safely,
    it doesn't crash).
    """


class LLMOutputValidationError(Exception):
    """The LLM response didn't parse into the expected schema.

    Per BUILD PROMPT section 29: callers should retry once, then fall back
    to a safe default (e.g. skip the semantic contribution and flag it for
    human review) rather than let malformed output drive downstream logic.
    """

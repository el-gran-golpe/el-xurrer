class RateLimitError(Exception):
    def __init__(self, message="Rate limit", cooldown_seconds=3600):
        super().__init__(message)
        self.cooldown_seconds: int = cooldown_seconds


class NoCandidateModelsError(RuntimeError):
    """
    Raised by `ModelRouter.get_response` when at least one provider group
    had a configured API key (so the router is not simply unconfigured),
    but every candidate model for this prompt was filtered out — excluded
    by a caller (`exclude_model`), censored for sensitive content, or
    quota-exhausted without recovery — leaving zero candidates anywhere and
    no underlying request error to report.

    Distinct from the plain `RuntimeError` `get_response` still raises when
    no provider has any usable API key at all: that case means "this router
    instance is not configured", while this one means "it is configured,
    but nothing is eligible right now". `llm/retry.py:generate_with_retries`
    catches this alongside `ValueError` and treats it as one more invalid
    attempt, so a retry loop that temporarily excludes its only candidate
    (e.g. a sensitive prompt whose only uncensored provider is the paid
    fallback) still reaches the forced-fallback last attempt instead of
    aborting outright.
    """

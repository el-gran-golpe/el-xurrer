# We assume that these models are uncensored and can handle any type of content
UNCENSORED_MODEL_GUESSES: list[str] = ["deepseek", "grok"]

# Fallback cooldown when a provider's 429 response has no usable Retry-After header.
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60

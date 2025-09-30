# Base URL
GITHUB_MODELS_BASE = "https://models.github.ai"

# Endpoints for GitHub models
CATALOG_URL = f"{GITHUB_MODELS_BASE}/catalog/models"
CHAT_COMPLETIONS_URL = f"{GITHUB_MODELS_BASE}/inference/chat/completions"

# API version of GitHub models
API_VERSION = "2024-08-01-preview"  # TODO: not sure if this is correct or should I use 2022-11-28 version

# We assume that these models are uncensored and can handle any type of content
UNCENSORED_MODEL_GUESSES: list[str] = ["deepseek", "grok"]
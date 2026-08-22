from abc import ABC, abstractmethod
from typing import Any

from ai_content_pipeline.llm.routing.classification.constants import (
    UNCENSORED_MODEL_GUESSES,
)


class LLMProvider(ABC):
    """A chat-completions backend: lists its usable models and answers prompts."""

    provider_id: str
    is_paid: bool

    @abstractmethod
    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        """Return this provider's usable models, each shaped like:
        {"id": str, "limits": {"max_input_tokens": int, "max_output_tokens": int}}.
        """

    @abstractmethod
    def chat_completion(
        self,
        api_key: str,
        model_id: str,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        """Return the assistant reply.

        Raises RateLimitError on quota exhaustion, requests.HTTPError (400) when the
        request itself is rejected (e.g. unsupported JSON mode), or a generic Exception
        for anything else — callers rely on these three shapes to decide whether to
        retry, mark a capability unsupported, or fail over to the next candidate.
        """

    def is_model_censored(self, model_id: str) -> bool:
        return not any(
            keyword.lower() in model_id.lower() for keyword in UNCENSORED_MODEL_GUESSES
        )

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from loguru import logger

from llm.error_handlers.api_error_handler import ApiErrorHandler
from llm.error_handlers.exceptions import RateLimitError
from llm.routing.classification.constants import API_VERSION, CHAT_COMPLETIONS_URL


@dataclass
class LLMModel:
    identifier: str
    supports_json_format: Optional[bool]  # can be unknown until probed
    is_censored: bool
    api_key: str
    exhausted_until_datetime: Optional[datetime] = None
    elo: float = 1.0
    is_quota_exhausted: bool = False
    max_input_tokens: int = 0
    max_output_tokens: int = 0

    def get_model_response(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        logger.info("Using model: {}", self.identifier)
        return self._request_chat_completion(conversation, output_as_json)

    def _request_chat_completion(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        payload = {
            "model": self.identifier,
            "messages": conversation,
            **({"response_format": {"type": "json_object"}} if output_as_json else {}),
        }

        try:
            r = requests.post(
                CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=30
            )
            if r.status_code != 200:
                # Let the shared error handler decide if it's RateLimitError, HTTPError, etc.
                raise ApiErrorHandler().transform_api_error_to_exception(
                    r, self.identifier
                )
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except RateLimitError:
            # Crucial: don't sleep here. Let the router fail over.
            raise
        except Exception:
            # Propagate other errors so the router can decide to try the next model.
            raise

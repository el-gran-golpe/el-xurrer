from dataclasses import dataclass
from datetime import datetime
from time import sleep

import requests
from loguru import logger

from llm.error_handlers.api_error_handler import ApiErrorHandler
from llm.error_handlers.exceptions import RateLimitError
from llm.routing.classification.constants import API_VERSION, CHAT_COMPLETIONS_URL


@dataclass
class LLMModel:
    identifier: str
    supports_json_format: bool
    is_censored: bool
    api_key: str
    exhausted_until_datetime: datetime
    # cooldown_until: datetime
    # last_error: str
    # last_checked_at: datetime
    quota_exhausted_cooldown_seconds: int
    elo: float = 1.0  # Hypothetical IQ score for ranking purposes
    is_quota_exhausted: bool = False  # To track rate limit exhaustion
    max_input_tokens: int = 0
    max_output_tokens: int = 0

    def get_model_response(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        logger.info("Using model: {}", self.identifier)
        assistant_reply = self.get_response_from_github_models(
            conversation=conversation,
            output_as_json=output_as_json,
        )
        # assistant_reply = _clean_chain_of_thought(
        #     model=self.identifier, assistant_reply=assistant_reply
        # )
        return assistant_reply

    def get_response_from_github_models(
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

        data = None
        for attempt in range(3):
            try:
                r = requests.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload)
                data = r.json()
                if r.status_code != 200:
                    raise ApiErrorHandler().transform_json_probing_error_to_exception(
                        r, self.identifier
                    )
            except RateLimitError as e:
                cooldown_seconds = e.cooldown_seconds
                logger.warning(
                    "Model {} quota exhausted. Sleeping for Cooldown seconds: {}",
                    self.identifier,
                    cooldown_seconds,
                )
                sleep(cooldown_seconds)
                if attempt == 2:
                    raise
                continue

        # TODO: implement the case for ["response_format"] = {"type": "json_object"}
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

        return content

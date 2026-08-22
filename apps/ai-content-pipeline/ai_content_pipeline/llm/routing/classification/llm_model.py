from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger

from ai_content_pipeline.llm.routing.providers.base import LLMProvider


@dataclass
class LLMModel:
    identifier: str
    supports_json_format: Optional[bool]  # can be unknown until probed
    is_censored: bool
    api_key: str
    provider: LLMProvider
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
        return self.provider.chat_completion(
            self.api_key, self.identifier, conversation, output_as_json
        )

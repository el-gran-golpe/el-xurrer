from collections.abc import Callable
from typing import Any

import openai
import requests
from loguru import logger
from openai import OpenAI

from ai_content_pipeline.llm.error_handlers.api_error_handler import parse_retry_after
from ai_content_pipeline.llm.error_handlers.exceptions import RateLimitError
from ai_content_pipeline.llm.routing.classification.constants import (
    DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
)
from ai_content_pipeline.llm.routing.providers.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Any backend that speaks the OpenAI chat-completions wire format.

    Covers both a free provider with dynamic model discovery (e.g. OpenRouter,
    via catalog_url + free_model_filter) and a paid provider with a fixed,
    always-available model (e.g. DeepSeek, via static_models) — same transport,
    only the catalog source differs.
    """

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        is_paid: bool,
        catalog_url: str | None = None,
        free_model_filter: Callable[[dict[str, Any]], bool] | None = None,
        static_models: list[dict[str, Any]] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.is_paid = is_paid
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.free_model_filter = free_model_filter
        self.static_models = static_models

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        if self.static_models is not None:
            return self.static_models

        if self.catalog_url is None:
            raise RuntimeError(
                f"Provider {self.provider_id} has no catalog source configured"
            )

        resp = requests.get(self.catalog_url, timeout=30)
        resp.raise_for_status()
        raw_models = resp.json().get("data", [])
        if self.free_model_filter is not None:
            raw_models = [m for m in raw_models if self.free_model_filter(m)]

        catalog: list[dict[str, Any]] = []
        for model in raw_models:
            model_id = model.get("id")
            if model_id is None:
                continue
            top_provider = model.get("top_provider") or {}
            catalog.append(
                {
                    "id": model_id,
                    "limits": {
                        "max_input_tokens": model.get("context_length", 0),
                        "max_output_tokens": top_provider.get(
                            "max_completion_tokens", 0
                        ),
                    },
                }
            )

        logger.debug("Fetched {} models from {}", len(catalog), self.provider_id)
        return catalog

    def chat_completion(
        self,
        api_key: str,
        model_id: str,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        logger.info("Using model: {} ({})", model_id, self.provider_id)
        client = OpenAI(api_key=api_key, base_url=self.base_url)

        try:
            response = client.chat.completions.create(  # type: ignore[call-overload]
                model=model_id,
                messages=conversation,  # type: ignore[arg-type]
                response_format=(
                    {"type": "json_object"} if output_as_json else {"type": "text"}
                ),
                stream=False,
            )
        except openai.RateLimitError as e:
            headers = e.response.headers if e.response is not None else {}
            cooldown = parse_retry_after(headers, DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)
            raise RateLimitError(
                message=f"Rate limited by {self.provider_id} for model {model_id}",
                cooldown_seconds=cooldown,
            ) from e
        except openai.BadRequestError as e:
            bad_request_response = requests.Response()
            bad_request_response.status_code = 400
            raise requests.HTTPError(
                f"Bad request for model {model_id} on {self.provider_id}",
                response=bad_request_response,
            ) from e

        if response.choices is None or len(response.choices) == 0:
            raise RuntimeError(
                f"{self.provider_id} returned no choices for model {model_id}"
            )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(
                f"{self.provider_id} returned no content for model {model_id}"
            )
        return content


OPENROUTER_PROVIDER = OpenAICompatibleProvider(
    provider_id="openrouter",
    base_url="https://openrouter.ai/api/v1",
    is_paid=False,
    catalog_url="https://openrouter.ai/api/v1/models",
    free_model_filter=lambda m: m.get("pricing", {}).get("prompt") == "0"
    or str(m.get("id", "")).endswith(":free"),
)

DEEPSEEK_PROVIDER = OpenAICompatibleProvider(
    provider_id="deepseek",
    base_url="https://api.deepseek.com/v1",
    is_paid=True,
    static_models=[{"id": "deepseek-chat"}],
)

import os
import random
from typing import Any, Tuple

from openai import OpenAI
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential


def get_llm_client(
    *,
    github_api_keys: list[str],
    openai_api_keys: list[str],
    model: str,
    free_api: bool,
    MODEL_BY_BACKEND: dict[str, str],
    OPENAI: str,
    AZURE: str,
) -> Tuple[Any, str, bool]:
    """
    Return (client, active_backend, using_paid_api) for the resolved backend.

    using_paid_api mirrors the previous class field logic (inverse of free_api).
    """
    backend = MODEL_BY_BACKEND.get(model, OPENAI)

    if backend == AZURE:
        endpoint = os.environ.get("AZURE_INFERENCE_ENDPOINT")
        key = os.environ.get("AZURE_INFERENCE_KEY")
        if not endpoint or not key:
            raise RuntimeError("Azure inference endpoint/key not set in environment")
        client = ChatCompletionsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        return client, AZURE, (not free_api)

    # Default / OpenAI path
    if not openai_api_keys:
        raise RuntimeError("No OpenAI API keys available")

    api_key = random.choice(openai_api_keys)
    base_url = os.environ.get("OPENAI_BASE_URL")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    return client, OPENAI, (not free_api)

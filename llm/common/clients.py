import os
import random
from typing import Any, Optional

from openai import OpenAI
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential


class LLMClientManager:
    """
    Manages LLM clients for Azure and OpenAI backends.
    """

    def __init__(self, github_api_keys: list[str], openai_api_keys: list[str]):
        self.github_api_keys = github_api_keys
        self.openai_api_keys = openai_api_keys

        self.client: Optional[Any] = None
        self.active_backend: Optional[str] = None
        self.using_paid_api: bool = False

    def get_client(
        self,
        model: str,
        free_api: bool,
        MODEL_BY_BACKEND: dict[str, str],
        OPENAI: str,
        AZURE: str,
    ) -> Any:
        """
        Returns a client instance for the given model by resolving the backend.
        """
        backend = MODEL_BY_BACKEND.get(model, OPENAI)
        if backend == AZURE:
            endpoint = os.environ.get("AZURE_INFERENCE_ENDPOINT")
            key = os.environ.get("AZURE_INFERENCE_KEY")
            if not endpoint or not key:
                raise RuntimeError(
                    "Azure inference endpoint/key not set in environment"
                )
            client = ChatCompletionsClient(
                endpoint=endpoint, credential=AzureKeyCredential(key)
            )
            self.client = client
            self.active_backend = AZURE
            self.using_paid_api = not free_api
            return client
        elif backend == OPENAI:
            if not self.openai_api_keys:
                raise RuntimeError("No OpenAI API keys available")
            api_key = random.choice(self.openai_api_keys)
            base_url = os.environ.get("OPENAI_BASE_URL", None)
            client = (
                OpenAI(api_key=api_key, base_url=base_url)
                if base_url
                else OpenAI(api_key=api_key)
            )
            self.client = client
            self.active_backend = OPENAI
            self.using_paid_api = not free_api
            return client
        else:
            if not self.openai_api_keys:
                raise RuntimeError("No OpenAI API keys available")
            api_key = random.choice(self.openai_api_keys)
            client = OpenAI(api_key=api_key)
            self.client = client
            self.active_backend = OPENAI
            self.using_paid_api = not free_api
            return client

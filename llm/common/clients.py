from openai import OpenAI
import random


class LLMClientManager:
    """
    Manages LLM clients for Azure and OpenAI backends.
    """

    def __init__(self, github_api_keys: list[str], openai_api_keys: list[str]):
        self.github_api_keys = github_api_keys
        self.openai_api_keys = openai_api_keys

        self.client = None
        self.active_backend = None
        self.using_paid_api = False

    def get_client(self, model, free_api, MODEL_BY_BACKEND, OPENAI, AZURE):
        backend = MODEL_BY_BACKEND[model]
        if not free_api:
            assert backend == OPENAI, "Paid API is only available for OpenAI models"
        if (
            self.active_backend == backend
            and self.client
            and self.using_paid_api == (not free_api)
        ):
            return self.client
        if backend == OPENAI:
            return self.get_new_client_openai(free_api=free_api)
        elif backend == AZURE:
            return self.get_new_client_azure()
        else:
            raise NotImplementedError(f"Backend not implemented: {backend}")

    def get_new_client_openai(self, free_api=True):
        if free_api:
            api_key = random.choice(self.github_api_keys)
            base_url = "https://models.inference.ai.azure.com"
        else:
            api_key = random.choice(self.openai_api_keys)
            base_url = None

        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.active_backend = "openai"
        self.using_paid_api = not free_api
        return self.client

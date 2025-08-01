from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from openai import OpenAI


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

    def get_client(self, model, paid_api, MODEL_BY_BACKEND, OPENAI, AZURE):
        backend = MODEL_BY_BACKEND[model]
        if paid_api:
            assert backend == OPENAI, "Paid API is only available for OpenAI models"
        if (
            self.active_backend == backend
            and self.client
            and self.using_paid_api == paid_api
        ):
            return self.client
        if backend == OPENAI:
            return self.get_new_client_openai(paid_api)
        elif backend == AZURE:
            return self.get_new_client_azure()
        else:
            raise NotImplementedError(f"Backend not implemented: {backend}")

    def get_new_client_azure(self):
        github_api_key = self.github_api_keys.random.choice()

        self.client = ChatCompletionsClient(
            endpoint="https://models.inference.ai.azure.com",
            credential=AzureKeyCredential(github_api_key),
        )
        self.active_backend = "azure"
        self.using_paid_api = False
        return self.client

    def get_new_client_openai(self, paid_api=False):
        # First of all, try to use the GitHub API key if available (Is free)
        # We are routing to azure first because it's free using our GitHub api keys and also because azure api is
        # compatible with OpenAI's API
        if not paid_api:
            api_key = self.api_keys_manager.get_random_github_api_key()
            base_url = "https://models.inference.ai.azure.com"
        else:
            api_key = self.api_keys_manager.get_openia_key()
            base_url = None
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key.api_key,
        )
        self.active_backend = "openai"
        self.using_paid_api = paid_api
        return self.client

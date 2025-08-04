# picks uncensored vs censored vs fallback
from typing import List, Literal
from llm.management.github_models_client import GitHubModelsClient
from llm.routing.content_classifier import ContentClassifier


class ModelRoutingPolicy:
    def __init__(
        self,
        github_client: GitHubModelsClient,
        uncensored_tag: str = "uncensored",
        censored_tag: str = "censored",
    ):
        self.client = github_client
        self.classifier = ContentClassifier()
        # Tag your model IDs appropriately (could load from constants or metadata)
        self.uncensored_tag = uncensored_tag
        self.censored_tag = censored_tag

    def ordered_models(self, prompt_text: str) -> List[str]:
        # 1. Fetch currently available models
        all_models = self.client.get_available_models()
        # 2. Partition into uncensored vs censored based on naming convention or metadata
        uncensored = [m for m in all_models if self.uncensored_tag in m.lower()]
        censored = [m for m in all_models if self.censored_tag in m.lower()]
        fallback = [m for m in all_models if m not in uncensored + censored]

        # 3. Classify the prompt
        category: Literal["hot", "general"] = self.classifier.classify_text(prompt_text)
        if category == "hot":
            return censored + fallback
        return uncensored + fallback

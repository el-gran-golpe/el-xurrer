from typing import Optional

from llm.routing.classification.model_classifier import ModelClassifier
from llm.routing.classification.llm_model import LLMModel
from main_components.common.types import PromptItem
from loguru import logger


class ModelRouter:
    def __init__(
        self,
        github_api_keys: list[str],
        openai_api_keys: list[str],
    ):
        self.github_api_keys = github_api_keys
        self.openai_api_keys = openai_api_keys
        # Each ModelsClassifier is tied to a specific GitHub API key
        self.github_classifiers: list[ModelClassifier] = [
            ModelClassifier(k) for k in self.github_api_keys
        ]

    def initialize_model_classifiers(
        self,
        models_to_scan: Optional[int] = None,  # None means scan all
    ) -> None:
        for classifier in self.github_classifiers:
            classifier.populate_models_catalog(models_to_scan=models_to_scan)

    def get_best_available_model(self, prompt_item: PromptItem) -> LLMModel:
        for classifier in self.github_classifiers:
            try:
                model = classifier.get_best_model(prompt_item)
                return model

            except Exception as e:
                logger.warning("ModelClassifier failed with error: {}", e)
                raise

        # If we reach here, no classifier returned a model — fail explicitly.
        logger.error("No available Github model found after trying all classifiers.")
        # Try OpenAI classifiers as a fallback
        # for classifier in self.openai_classifiers:
        #     try:
        #         model = classifier.get_best_model(prompt_item)
        #         return model
        #
        #     except Exception as e:
        #         logger.warning("OpenAI ModelClassifier failed with error: {}", e)
        #         continue

        raise RuntimeError("No available model found.")

    # def mark_model_as_quota_exhausted(self, model: LLMModel) -> None:
    #    for classifier in self.github_classifiers:
    #        classifier.mark_model_as_quota_exhausted(model)

    def get_response(self, prompt_item: PromptItem) -> str:
        model = self.get_best_available_model(prompt_item=prompt_item)
        conversation = [
            {"role": "system", "content": prompt_item.system_prompt},
            {"role": "user", "content": prompt_item.prompt},
        ]
        output_as_json = prompt_item.output_as_json
        # TODO: get_model_response should return a response or raise an exception that the model router can handle
        return model.get_model_response(conversation, output_as_json)

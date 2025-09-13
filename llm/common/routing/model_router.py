from pathlib import Path
from typing import Optional

from llm.common.api_keys import api_keys
from llm.common.routing.classification.model_classifier import ModelClassifier, LLMModel
from llm.utils import load_and_prepare_prompts
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
        # Multiple classifiers (one per GitHub key)
        self.github_classifiers: list[ModelClassifier] = [
            ModelClassifier(k) for k in self.github_api_keys
        ]

    def initialize_model_classifiers(self, models_to_scan: Optional[int]) -> None:
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
        # TODO: at some point, I would like to tell modelrouter to use api instead of free github models (just in case)
        logger.error("No available Github model found after trying all classifiers.")
        # Try OpenAI classifiers as a fallback
        for classifier in self.openai_classifiers:
            try:
                model = classifier.get_best_model(prompt_item)
                return model

            except Exception as e:
                logger.warning("OpenAI ModelClassifier failed with error: {}", e)
                continue

        raise RuntimeError("No available model found.")

    def mark_model_as_quota_exhausted(self, model: LLMModel) -> None:
        for classifier in self.github_classifiers:
            classifier.mark_model_as_quota_exhausted(model)


    def get_response(self, prompt_item: PromptItem) -> str:
        model = self.get_best_available_model(prompt_item=prompt_item)
        conversation = [
            {"role": "system", "content": prompt_item.system_prompt},
            {"role": "user", "content": prompt_item.prompt},
        ]
        output_as_json = prompt_item.output_as_json
        
        # TODO: get_model_response should return a response or raise an exception that the model router can handle
        assistant_reply, finish_reason = model.get_model_response(conversation, output_as_json)

        
        return assistant_reply




if __name__ == "__main__":
    pass
    github_api_keys = api_keys.extract_github_keys()
    openai_api_keys = api_keys.extract_openai_keys()
    prompt_items: list[PromptItem] = load_and_prepare_prompts(
        # prompt_json_template_path=Path(
        #     r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\meta\inputs\laura_vigne.json"
        # ),
        prompt_json_template_path=Path(
            "/home/moises/repos/gg2/el-xurrer/resources/laura_vigne/meta/inputs/laura_vigne.json"
        ),
        previous_storyline="Laura Vigne commited taux fraud and moved to Switzerland.",
    )
    router = ModelRouter(github_api_keys, openai_api_keys)
    router.initialize_model_classifiers(models_to_scan=5)  # TODO make sure this ends if we scan everything
    # catalog = router.fetch_github_models_catalog()
    best = router.get_best_available_model(prompt_items[0])
    logger.success("BEST MODEL: {}", best)

    quota = router.check_github_models_quota(best)
    logger.info("Quota snapshot: {}", quota)

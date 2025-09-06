from llm.common.routing.classification.model_classifier import ModelClassifier, LLMModel
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

    def _initialize_classifier(self) -> None:
        for classifier in self.github_classifiers:
            classifier.populate_models_catalog()

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


if __name__ == "__main__":
    pass
    # github_api_keys = api_keys.extract_github_keys()
    # openai_api_keys = api_keys.extract_openai_keys()
    # prompt_items: list[PromptItem] = load_and_prepare_prompts(
    #     prompt_json_template_path=Path(
    #         r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\fanvue\inputs\laura_vigne.json"
    #     ),
    #     previous_storyline="Laura Vigne commited taux fraud and moved to Switzerland.",
    # )
    # router = ModelRouter(github_api_keys, openai_api_keys)
    # # catalog = router.fetch_github_models_catalog()
    # best = router.get_best_available_model(prompt_items[0])
    # logger.success("BEST MODEL: {}", best)
    #
    # quota = router.check_github_models_quota(best)
    # logger.info("Quota snapshot: {}", quota)

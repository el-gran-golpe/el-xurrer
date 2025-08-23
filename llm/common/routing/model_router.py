import time
import requests
from loguru import logger

from llm.utils import load_and_prepare_prompts
from main_components.common.types import PromptItem
from pathlib import Path
from llm.common.api_keys import api_keys
from typing import Mapping, Any


GITHUB_MODELS_BASE = "https://models.github.ai"
CATALOG_URL = f"{GITHUB_MODELS_BASE}/catalog/models"
CHAT_COMPLETIONS_URL = f"{GITHUB_MODELS_BASE}/inference/chat/completions"
API_VERSION = "2022-11-28"


class ModelRouter:
    def __init__(
        self,
        github_api_keys: list[str],
        openai_api_keys: list[str],
    ):
        self.github_api_keys = github_api_keys
        self.openai_api_keys = openai_api_keys
        self._model_classifier = ModelClassifier(
            github_api_key=github_api_keys[0]
        )  # TODO: Handle multiple model classifiers for multiple keys

    def initialize_classifier(self):
        self._model_classifier.populate_models_catalog()

    def get_best_available_model(self, prompt_item: PromptItem) -> str:
        return self._model_classifier.get_best_model(prompt_item)

    def mark_model_as_quota_exhausted(self, model: str):
        self._model_classifier.mark_model_as_quota_exhausted(model)


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

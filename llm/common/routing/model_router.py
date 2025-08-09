from typing import Literal

from llm.common.routing.content_classifier import ContentClassifier
from llm.types import PromptSpecification
from llm.management.usage_tracker import ModelUsageTracker
from llm.management.key_manager import KeyManager


class ModelRouter:
    """
    Handles model selection (censored, uncensored or fallback/json structuring), and managing the model MANA (;P).

    This class is responsible for routing requests to the appropriate AI model based on the content type
    and the specifications provided in the prompt. It also tracks usage and manages API keys.
    """

    CATALOG_URL = "https://models.github.ai/catalog/models"

    def __init__(self, pat_keys):
        self.key_manager = KeyManager(pat_keys)
        self.usage = ModelUsageTracker()
        self.daily_quotas: dict[str, int] = {}
        self._load_usage()
        self.classifier = ContentClassifier()
        self.models_catalog = self._fetch_catalog()  # type: ignore

    def _sort_by_intelligence(self, models: list[dict]) -> list[dict]:
        # Example: sort by a 'score' field, or by model name heuristics
        return sorted(models, key=lambda m: m.get("score", 0), reverse=True)

    def get_models(
        self, prompt_spec: PromptSpecification, content_type: Literal["hot", "innocent"]
    ) -> list[str]:
        require_json = getattr(prompt_spec, "json", False)
        available = self.get_available_models()
        censored = [m for m in available if "censored" in m["id"].lower()]
        uncensored = [m for m in available if "uncensored" in m["id"].lower()]
        json_models = [m for m in available if m.get("supports_json", False)]

        # Pick censored for hot, uncensored for innocent
        if content_type == "hot":
            candidates = censored
        else:
            candidates = uncensored

        # If JSON required, filter for JSON support
        if require_json:
            candidates = [m for m in candidates if m in json_models] or json_models

        # Sort by intelligence
        candidates = self._sort_by_intelligence(candidates)

        # Fallback to all available if none found
        if not candidates:
            candidates = self._sort_by_intelligence(available)

        return [m["id"] for m in candidates]

    def get_available_models(self) -> list[dict]:
        # Only return models with free tier left
        available = []
        for m in self.models_catalog:
            mid = m["id"]
            limit = m.get("free_daily_limit", 50)
            used = self.daily_quotas.get(mid, 0)
            if used < limit:
                available.append(m)
        return available

    # def record_usage(self, model_id: str, success: bool, latency: float):
    #     self.daily_quotas[model_id] = self.daily_quotas.get(model_id, 0) + 1
    #     self._save_usage()
    #     self.usage.record(model_id, success, latency)

    def _load_usage(self) -> None:
        # TODO: implement loading usage from storage
        pass

    def _fetch_catalog(self) -> list[dict]:
        # TODO: implement fetching the model catalog
        # For now, return an empty list or mock data
        return []

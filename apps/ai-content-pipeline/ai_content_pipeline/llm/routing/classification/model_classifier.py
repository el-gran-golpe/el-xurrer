from datetime import timedelta
from typing import Optional

from loguru import logger

from ai_content_pipeline.llm.routing.classification.llm_model import LLMModel
from ai_content_pipeline.llm.routing.classification.model_cache import ModelCache
from ai_content_pipeline.llm.routing.providers.base import LLMProvider
from ai_content_pipeline.domain.types import PromptItem
from ai_content_pipeline.config import settings


class ModelClassifier:
    """
    This class classifies models based on: elo, json schema and censorship.
    This class should return a ranking of models available for a particular provider API key:
    that is, it should return a dict of models, where the keys of this dict is elo, json schema and
    if it is censored or uncensored.
    """

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str,
        model_cache: ModelCache | None = None,
    ):
        self.provider = provider
        self.api_key: str = api_key
        self.free_catalog: list[dict] = []
        # This is the distilled catalog of models we will use for routing
        self.models_catalog: dict[str, LLMModel] = {}
        self.model_cache = model_cache or ModelCache(
            cache_dir=settings.model_cache_dir,
            catalog_ttl=timedelta(hours=settings.model_cache_ttl_hours),
        )

    @property
    def provider_id(self) -> str:
        return self.provider.provider_id

    # NEW: give the router a *list* of candidates, not just one.
    def get_ranked_models(self, prompt_item: PromptItem) -> list[LLMModel]:
        output_as_json = prompt_item.output_as_json
        is_sensitive_content = prompt_item.is_sensitive_content

        ranked = []
        for model in self._get_models_sorted_by_elo():
            # Skip if exhausted and not recovered
            if not self._is_quota_recovered(model):
                continue
            if is_sensitive_content and model.is_censored:
                continue
            if output_as_json and model.supports_json_format is False:
                continue
            ranked.append(model)
        return ranked

    # Backwards-compat, used nowhere after router change, but fine to keep
    def get_best_model(self, prompt_item: PromptItem) -> LLMModel:
        candidates = self.get_ranked_models(prompt_item)
        if not candidates:
            raise RuntimeError("No suitable model found for the given prompt item.")
        return candidates[0]

    def populate_models_catalog(
        self,
        models_to_scan: Optional[int],
        free_catalog: list[dict] | None = None,
    ):
        if free_catalog is None:
            self.free_catalog = self.model_cache.get_catalog(
                self.provider_id, lambda: self.provider.fetch_catalog(self.api_key)
            )
        else:
            self.free_catalog = free_catalog

        self.models_catalog = {}
        models = self.free_catalog
        for model in models[0:models_to_scan]:
            model_id = model.get("id")

            if model_id is None:
                continue

            max_input_tokens = model.get("limits", {}).get("max_input_tokens")
            max_output_tokens = model.get("limits", {}).get("max_output_tokens")

            # Default values if not provided for a LLMModel
            llm_model_params = {
                "is_quota_exhausted": False,  # To track rate limit exhaustion
                "exhausted_until_datetime": None,
                "supports_json_format": None,  # Unknown until tested
                "is_censored": self.provider.is_model_censored(model_id),
                "api_key": self.api_key,
                "provider": self.provider,
                "elo": 1.0,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
            }

            cached_state = self.model_cache.get_model_state(
                self.provider_id, self.api_key, model_id
            )
            if cached_state is not None:
                llm_model_params["supports_json_format"] = (
                    cached_state.supports_json_format
                )
                exhausted_until = cached_state.exhausted_until_datetime
                if (
                    exhausted_until is not None
                    and self.model_cache.now() < exhausted_until
                ):
                    llm_model_params["is_quota_exhausted"] = True
                    llm_model_params["exhausted_until_datetime"] = exhausted_until

            self.models_catalog[model_id] = LLMModel(
                identifier=model_id,
                **llm_model_params,
            )

    def mark_model_as_quota_exhausted(
        self, model: LLMModel, cooldown_seconds: int
    ) -> None:
        model.is_quota_exhausted = True
        model.exhausted_until_datetime = self.model_cache.now() + timedelta(
            seconds=cooldown_seconds
        )
        self.model_cache.set_model_exhausted_until(
            self.provider_id,
            self.api_key,
            model.identifier,
            model.exhausted_until_datetime,
        )
        logger.info(
            "Marked {} as exhausted until {}",
            model.identifier,
            model.exhausted_until_datetime,
        )

    def mark_model_json_support(
        self, model: LLMModel, supports_json_format: bool
    ) -> None:
        model.supports_json_format = supports_json_format
        self.model_cache.set_model_json_support(
            self.provider_id,
            self.api_key,
            model.identifier,
            supports_json_format,
        )

    def _get_model_elo(self, model_id: str) -> float:
        return self.models_catalog[model_id].elo

    def _get_models_sorted_by_elo(self) -> list[LLMModel]:
        return sorted(self.models_catalog.values(), key=lambda m: m.elo, reverse=True)

    def _is_quota_recovered(self, model: LLMModel) -> bool:
        if not model.is_quota_exhausted:
            return True
        if model.exhausted_until_datetime is None:
            return True
        if self.model_cache.now() >= model.exhausted_until_datetime:
            model.is_quota_exhausted = False
            model.exhausted_until_datetime = None
            self.model_cache.set_model_exhausted_until(
                self.provider_id,
                self.api_key,
                model.identifier,
                None,
            )
            logger.info("Model {} quota has recovered", model.identifier)
            return True
        logger.debug(
            "Model {} still exhausted until {}",
            model.identifier,
            model.exhausted_until_datetime,
        )
        return False

from datetime import timedelta
from time import sleep
from typing import Optional, Generator

from loguru import logger

from ai_content_pipeline.llm.error_handlers.exceptions import RateLimitError
from ai_content_pipeline.llm.routing.classification.llm_model import LLMModel
from ai_content_pipeline.llm.routing.classification.model_classifier import (
    ModelClassifier,
)
from ai_content_pipeline.llm.routing.classification.model_cache import ModelCache
from ai_content_pipeline.llm.routing.providers.base import LLMProvider
from ai_content_pipeline.llm.routing.providers.openai_compatible_provider import (
    DEEPSEEK_PROVIDER,
    OPENROUTER_PROVIDER,
)
from ai_content_pipeline.domain.types import PromptItem
from ai_content_pipeline.config import settings
from ai_content_pipeline.llm.utils.response import decode_json_from_message

from requests import HTTPError

INLINE_WAIT_THRESHOLD_SECONDS = 60
MAX_INLINE_WAIT_RETRIES = (
    1  # avoid infinite loops if the API keeps saying "come back soon"
)


class ModelRouter:
    def __init__(
        self,
        free_provider_keys: dict[str, list[str]],
        deepseek_api_key: str,
        model_cache: ModelCache | None = None,
        free_providers: list[LLMProvider] | None = None,
        deepseek_provider: LLMProvider | None = None,
    ):
        self.model_cache = model_cache or ModelCache(
            cache_dir=settings.model_cache_dir,
            catalog_ttl=timedelta(hours=settings.model_cache_ttl_hours),
        )

        free_providers = free_providers or [OPENROUTER_PROVIDER]
        self.deepseek_provider = deepseek_provider or DEEPSEEK_PROVIDER

        # One classifier group per free provider, tried in order; DeepSeek is
        # always appended last as the paid fallback.
        self.classifier_groups: list[tuple[str, list[ModelClassifier]]] = [
            (
                provider.provider_id,
                [
                    ModelClassifier(provider, key, model_cache=self.model_cache)
                    for key in free_provider_keys.get(provider.provider_id, [])
                ],
            )
            for provider in free_providers
        ]
        self.classifier_groups.append(
            (
                self.deepseek_provider.provider_id,
                [
                    ModelClassifier(
                        self.deepseek_provider,
                        deepseek_api_key,
                        model_cache=self.model_cache,
                    )
                ],
            )
        )

        # Per-provider cursor to remember which key worked last; rotate on shortages.
        self._key_cursor: dict[str, int] = {
            provider_id: 0 for provider_id, _ in self.classifier_groups
        }

    def classifiers_for(self, provider_id: str) -> list[ModelClassifier]:
        for group_provider_id, classifiers in self.classifier_groups:
            if group_provider_id == provider_id:
                return classifiers
        return []

    def initialize_model_classifiers(
        self,
        models_to_scan: Optional[int] = None,  # None means scan all
        force_refresh: bool = False,
    ) -> None:
        for provider_id, classifiers in self.classifier_groups:
            if not classifiers:
                continue

            first_classifier = classifiers[0]

            def fetch_catalog(clf: ModelClassifier = first_classifier) -> list[dict]:
                return clf.provider.fetch_catalog(clf.api_key)

            free_catalog = self.model_cache.get_catalog(
                provider_id,
                fetch_catalog,
                force_refresh=force_refresh,
            )

            for classifier in classifiers:
                classifier.populate_models_catalog(
                    models_to_scan=models_to_scan,
                    free_catalog=free_catalog,
                )

            # Debug: log models for each classifier after population
            for idx, classifier in enumerate(classifiers):
                catalog = classifier.models_catalog
                logger.debug(
                    "{} classifier index {} populated with {} models",
                    provider_id,
                    idx,
                    len(catalog),
                )
                for model_id, model in catalog.items():
                    logger.debug(
                        "  • {} | ELO: {:.2f} | JSON: {} | Censored: {} | Quota exhausted: {} | Max input: {} | Max output: {}",
                        model_id,
                        model.elo,
                        model.supports_json_format,
                        model.is_censored,
                        model.is_quota_exhausted,
                        model.max_input_tokens,
                        model.max_output_tokens,
                    )

    def get_response(self, prompt_item: PromptItem) -> str:
        conversation = [
            {"role": "system", "content": prompt_item.system_prompt},
            {"role": "user", "content": prompt_item.prompt},
        ]
        output_as_json = prompt_item.output_as_json

        # Try each provider group in order (free providers first, paid DeepSeek
        # last); the last group's failure is what surfaces if everything fails.
        last_error: Optional[Exception] = None
        for provider_id, classifiers in self.classifier_groups:
            reply, _, group_error = self._try_provider_group(
                provider_id, classifiers, conversation, output_as_json, prompt_item
            )
            if reply:
                return reply
            if group_error is not None:
                last_error = group_error

        if last_error is not None:
            raise last_error
        raise RuntimeError("No provider is configured with any usable API key")

    # ---------------- helpers ----------------

    def _try_provider_group(
        self,
        provider_id: str,
        classifiers: list[ModelClassifier],
        conversation: list[dict[str, str]],
        output_as_json: bool,
        prompt_item: PromptItem,
    ) -> tuple[Optional[str], Optional[tuple[LLMModel, float]], Optional[Exception]]:
        """Try all API keys/models for one provider, in rotation."""

        soonest: Optional[tuple[LLMModel, float]] = None
        first_error: Optional[Exception] = None

        for i in self._iter_key_indices_from_cursor(provider_id, len(classifiers)):
            classifier = classifiers[i]
            candidates = self._collect_candidates_for_classifier(
                classifier, prompt_item
            )

            if not candidates:
                continue

            reply, key_soonest, key_first_error = self._try_candidates_for_classifier(
                classifier, candidates, conversation, output_as_json
            )

            soonest = self._pick_soonest(soonest, key_soonest)

            if reply:
                self._key_cursor[provider_id] = i
                return reply, soonest, first_error

            if first_error is None:
                first_error = key_first_error

        return None, soonest, first_error

    def _iter_key_indices_from_cursor(
        self, provider_id: str, num_keys: int
    ) -> Generator[int, None, None]:
        """Yield API key indices for one provider in circular rotation order, starting from the last successful key."""
        if num_keys == 0:
            return
        start = self._key_cursor[provider_id] % num_keys
        for i in range(num_keys):
            yield (start + i) % num_keys

    def _collect_candidates_for_classifier(
        self, clf: ModelClassifier, prompt_item: PromptItem
    ) -> list[LLMModel]:
        """Get ranked, capability-filtered models for one key; highest ELO first."""
        models = clf.get_ranked_models(prompt_item)
        models.sort(key=lambda m: m.elo, reverse=True)
        logger.debug(
            "Key classifier collected {} candidates: {}",
            len(models),
            [f"{m.identifier} (ELO: {m.elo})" for m in models],
        )
        return models

    def _try_candidates_for_classifier(
        self,
        classifier: ModelClassifier,
        candidates: list[LLMModel],
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> tuple[Optional[str], Optional[tuple[LLMModel, float]], Optional[Exception]]:
        """
        Try all candidates for one classifier.
        Returns: (reply|None, soonest_eta_pair|None, first_error|None)
        """
        first_error: Optional[Exception] = None
        soonest: Optional[tuple[LLMModel, float]] = None

        for model in candidates:
            inline_retries = 0
            while True:
                try:
                    reply = model.get_model_response(conversation, output_as_json)
                    if output_as_json:
                        try:
                            decode_json_from_message(reply)
                        except ValueError as json_error:
                            # The API accepted response_format=json_object but the
                            # model didn't actually return valid JSON. Don't trust
                            # this candidate's json support and fail over.
                            logger.warning(
                                "Model {} returned invalid JSON despite JSON mode — "
                                "marking unsupported and failing over: {}",
                                model.identifier,
                                json_error,
                            )
                            classifier.mark_model_json_support(model, False)
                            if first_error is None:
                                first_error = json_error
                            break  # next candidate
                        classifier.mark_model_json_support(model, True)
                    return reply, soonest, first_error

                except RateLimitError as e:
                    cooldown = max(0, int(e.cooldown_seconds or 0))
                    if (
                        cooldown <= INLINE_WAIT_THRESHOLD_SECONDS
                        and inline_retries < MAX_INLINE_WAIT_RETRIES
                    ):
                        logger.info(
                            "Inline wait {}s for {} due to short cooldown (retry {}/{})",
                            cooldown,
                            model.identifier,
                            inline_retries + 1,
                            MAX_INLINE_WAIT_RETRIES,
                        )
                        sleep(cooldown)
                        inline_retries += 1
                        continue

                    # long cooldown or retries exhausted: mark exhausted and move on
                    logger.warning(
                        "Quota exhausted on {} (cooldown {}s) — marking exhausted and failing over",
                        model.identifier,
                        cooldown,
                    )
                    classifier.mark_model_as_quota_exhausted(model, cooldown)

                    eta = float(cooldown)
                    soonest = self._pick_soonest(soonest, (model, eta))
                    if first_error is None:
                        first_error = e
                    break  # next candidate

                except HTTPError as e:
                    logger.error(
                        "Model {} failed with HTTP error: {}", model.identifier, e
                    )
                    if (
                        output_as_json
                        and e.response is not None
                        and e.response.status_code == 400
                    ):
                        classifier.mark_model_json_support(model, False)
                    if first_error is None:
                        first_error = e
                    break  # next candidate

                except Exception as e:
                    logger.error("Model {} failed with error: {}", model.identifier, e)
                    if first_error is None:
                        first_error = e
                    break  # next candidate

        # No candidate succeeded for this key
        return None, soonest, first_error

    @staticmethod
    def _pick_soonest(
        a: Optional[tuple[LLMModel, float]], b: Optional[tuple[LLMModel, float]]
    ) -> Optional[tuple[LLMModel, float]]:
        if a is None:
            return b
        if b is None:
            return a
        return b if b[1] < a[1] else a

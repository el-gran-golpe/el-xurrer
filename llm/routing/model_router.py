from time import sleep
from typing import Optional, Generator

from loguru import logger

from llm.error_handlers.exceptions import RateLimitError
from llm.routing.classification.llm_model import LLMModel
from llm.routing.classification.model_classifier import ModelClassifier
from main_components.common.types import PromptItem

from openai import OpenAI

INLINE_WAIT_THRESHOLD_SECONDS = 60
MAX_INLINE_WAIT_RETRIES = (
    1  # avoid infinite loops if the API keeps saying "come back soon"
)


class ModelRouter:
    def __init__(self, github_api_keys: list[str], deepseek_api_key: str):
        self.github_api_keys = github_api_keys
        self.deepseek_api_key = deepseek_api_key

        # One classifier per GitHub API key
        self.github_classifiers: list[ModelClassifier] = [
            ModelClassifier(k) for k in self.github_api_keys
        ]

        # Cursor to remember which key worked last; we start at 0 and rotate on shortages
        self._github_key_cursor: int = 0

    def initialize_model_classifiers(
        self,
        models_to_scan: Optional[int] = None,  # None means scan all
    ) -> None:
        for classifier in self.github_classifiers:
            classifier.populate_models_catalog(models_to_scan=models_to_scan)

        # Debug: log models for each classifier after population
        for idx, classifier in enumerate(self.github_classifiers):
            catalog = classifier.models_catalog
            logger.debug(
                "Classifier index {} populated with {} models",
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

        # ---------- 1) Try all GitHub keys/models first ----------
        reply, soonest, first_error = self._try_github_models(
            conversation, output_as_json, prompt_item
        )
        if reply:
            return reply

        # ---------- 2) DeepSeek fallback if GitHub fully failed ----------
        return self._try_deepseek_fallback(
            conversation=conversation,
            output_as_json=output_as_json,
        )

    # ---------------- helpers ----------------

    def _try_github_models(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
        prompt_item: PromptItem,
    ) -> tuple[Optional[str], Optional[tuple[LLMModel, float]], Optional[Exception]]:
        """Try all GitHub API keys/models in rotation."""

        soonest: Optional[tuple[LLMModel, float]] = None
        first_error: Optional[Exception] = None

        for i in self._iter_key_indices_from_cursor():
            classifier = self.github_classifiers[i]
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
                self._github_key_cursor = i
                return reply, soonest, first_error

            if first_error is None:
                first_error = key_first_error

        return None, soonest, first_error

    def _iter_key_indices_from_cursor(self) -> Generator[int, None, None]:
        """Yield GitHub API key indices in circular rotation order, starting from the last successful key."""
        n = len(self.github_classifiers)
        start = self._github_key_cursor % max(1, n)
        for i in range(n):
            yield (start + i) % n

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

                except Exception as e:
                    logger.error("Model {} failed with error: {}", model.identifier, e)
                    if first_error is None:
                        first_error = e
                    break  # next candidate

        # No candidate succeeded for this key
        return None, soonest, first_error

    # ------------ deepseek helpers ------------

    def _try_deepseek_fallback(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        client = OpenAI(
            api_key=self.deepseek_api_key, base_url="https://api.deepseek.com/v1"
        )
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=conversation,
                response_format={"type": "json_object"}
                if output_as_json
                else {"type": "text"},
                stream=False,
            )
        except Exception as e:
            logger.error("DeepSeek API fallback failed with error: {}", e)
            raise e
        return response.choices[0].message.content

    @staticmethod
    def _pick_soonest(
        a: Optional[tuple[LLMModel, float]], b: Optional[tuple[LLMModel, float]]
    ) -> Optional[tuple[LLMModel, float]]:
        if a is None:
            return b
        if b is None:
            return a
        return b if b[1] < a[1] else a

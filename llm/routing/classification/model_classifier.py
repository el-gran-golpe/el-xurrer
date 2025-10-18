import json
import re
from time import sleep
from typing import Optional, Match, cast
from datetime import datetime, timedelta

import requests
from requests import HTTPError
from loguru import logger

from llm.error_handlers.api_error_handler import ApiErrorHandler
from llm.routing.classification.constants import (
    UNCENSORED_MODEL_GUESSES,
    API_VERSION,
    CATALOG_URL,
    CHAT_COMPLETIONS_URL,
)
from llm.routing.classification.llm_model import LLMModel
from main_components.common.types import PromptItem
from llm.error_handlers.exceptions import RateLimitError

INLINE_WAIT_THRESHOLD_SECONDS = 60
MAX_PROBE_INLINE_WAIT_RETRIES = 1


class ModelClassifier:
    """
    This class classifies models based on: elo, json schema and censorship.
    This class should return a ranking of models available for a particular GitHub API key:
    that is, it should return a dict of models, where the keys of this dict is elo, json schema and
    if it is censored or uncensored.
    """

    def __init__(
        self,
        github_api_key: str,
    ):
        self.github_api_key: str = github_api_key
        self.github_free_catalog: list[dict] = self._fetch_github_models_catalog()
        # This is the distilled catalog of models we will use for routing
        self.models_catalog: dict[str, LLMModel] = {}
        self.api_error_handler = ApiErrorHandler()

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

    def populate_models_catalog(self, models_to_scan: Optional[int]):
        models = self.github_free_catalog

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
                "is_censored": self._is_model_censored(model_id),
                "api_key": self.github_api_key,
                "elo": 1.0,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
            }

            try:
                # Check quota FIRST before any probing
                self._check_model_quota(model_id)
            except RateLimitError as e:
                logger.warning(
                    "Model {} quota exhausted during initial check. Cooldown seconds: {}",
                    model_id,
                    e.cooldown_seconds,
                )
                # Mark as exhausted but add to catalog
                llm_model_params["is_quota_exhausted"] = True
                llm_model_params["exhausted_until_datetime"] = (
                    datetime.now() + timedelta(seconds=e.cooldown_seconds)
                )
                self.models_catalog[model_id] = LLMModel(
                    identifier=model_id,
                    **llm_model_params,
                )
                continue
            except Exception as e:
                logger.error("Error while checking quota for model {}: {}", model_id, e)
                continue

            # If quota check passed, NOW probe JSON support
            try:
                llm_model_params["supports_json_format"] = (
                    self._supports_json_response_format(model_id)
                )
            # INFO: I want to encapsulate the exceptions on its own class handler, but I think is going to
            # be harder, so I will leave it like this for now.
            except RateLimitError as e:
                logger.warning(
                    "Model {} quota exhausted while probing JSON support. Cooldown seconds: {}",
                    model_id,
                    e.cooldown_seconds,
                )
                continue
            # TODO: If it's a 400 try to merge system prompt and prompt together
            except HTTPError as e:
                logger.error(
                    "HTTP error while probing JSON support for model {}: {}",
                    model_id,
                    e,
                )
                continue
            # TODO: Study those errors
            except Exception as e:
                logger.error(
                    "Error while probing JSON support for model {}: {}", model_id, e
                )
                continue

            self.models_catalog[model_id] = LLMModel(
                identifier=model_id,
                **llm_model_params,
            )

        # self._build_llm_arena_scoreboard_intersection() # TODO: this method should get the elos for the models in the leaderboard and update the model catalog with the current elo

    def mark_model_as_quota_exhausted(
        self, model: LLMModel, cooldown_seconds: int
    ) -> None:
        model.is_quota_exhausted = True
        model.exhausted_until_datetime = datetime.now() + timedelta(
            seconds=cooldown_seconds
        )
        logger.info(
            "Marked {} as exhausted until {}",
            model.identifier,
            model.exhausted_until_datetime,
        )

    def _fetch_github_models_catalog(self) -> list[dict]:
        headers = {
            "Authorization": f"Bearer {self.github_api_key}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        resp = requests.get(CATALOG_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        models = resp.json()

        logger.debug("Fetched {} models with GitHub key", len(models))
        for m in models:
            model_id = m.get("id")
            max_input_tokens = m.get("limits", {}).get("max_input_tokens", 0)
            max_output_tokens = m.get("limits", {}).get("max_output_tokens", 0)
            publisher = m.get("publisher", "<no-publisher>")
            tier = m.get("rate_limit_tier", "<no-tier>")
            supported_inputs = ",".join(m.get("supported_input_modalities", []))
            supported_outputs = ",".join(m.get("supported_output_modalities", []))
            logger.debug(
                " • {} | publisher={} | tier={} | supported_inputs=[{}] | supported_outputs=[{}], max_input_tokens={} | max_output_tokens={}",
                model_id,
                publisher,
                tier,
                supported_inputs,
                supported_outputs,
                max_input_tokens,
                max_output_tokens,
            )
        return models

    def _get_model_elo(self, model_id: str) -> float:
        return self.models_catalog[model_id].elo

    def _get_models_sorted_by_elo(self) -> list[LLMModel]:
        return sorted(self.models_catalog.values(), key=lambda m: m.elo, reverse=True)

    def _is_model_censored(self, model_id: str) -> bool:
        return not any(
            keyword.lower() in model_id.lower() for keyword in UNCENSORED_MODEL_GUESSES
        )

    # --- Helper 1: Does the LLMModel has available quota? ---
    def _check_model_quota(self, model_id: str) -> None:
        """
        Minimal POST to see if the model is currently usable. It's just a PING.
        On short cooldown (<=60s), wait inline and retry once.
        """
        headers = {
            "Authorization": f"Bearer {self.github_api_key}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Follow safety policies and refuse unsafe requests.",
                },
                {
                    "role": "user",
                    "content": "Connectivity check. Please reply with OK.",
                },
            ],
        }

        attempts = 0
        while True:
            attempts += 1
            r = requests.post(
                CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=20
            )
            if r.status_code == 200:
                return

            exc = self.api_error_handler.transform_api_error_to_exception(r, model_id)
            if isinstance(exc, RateLimitError):
                cooldown = max(0, int(exc.cooldown_seconds))
                if cooldown <= INLINE_WAIT_THRESHOLD_SECONDS and attempts <= (
                    1 + MAX_PROBE_INLINE_WAIT_RETRIES
                ):
                    logger.info(
                        "Quota check short cooldown {}s for {}, inline waiting then retrying...",
                        cooldown,
                        model_id,
                    )
                    sleep(cooldown)
                    continue
            # not a short cooldown or retries exhausted
            raise exc

    def _is_quota_recovered(self, model: LLMModel) -> bool:
        if not model.is_quota_exhausted:
            return True
        if model.exhausted_until_datetime is None:
            return True
        if datetime.now() >= model.exhausted_until_datetime:
            model.is_quota_exhausted = False
            model.exhausted_until_datetime = None
            logger.info("Model {} quota has recovered", model.identifier)
            return True
        logger.debug(
            "Model {} still exhausted until {}",
            model.identifier,
            model.exhausted_until_datetime,
        )
        return False

    # --- Helper 2: Does the LLMModel support json formatting? ---
    def _supports_json_response_format(self, model_id: str) -> Optional[bool]:
        """
        True if the model accepts response_format={'type': 'json_object'}.
        On short cooldown (<=60s), wait inline and retry once.
        """
        headers = {
            "Authorization": f"Bearer {self.github_api_key}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "Follow all safety policies. If unsafe, refuse briefly.",
                },
                {
                    "role": "user",
                    "content": 'Reply with a valid JSON object matching the schema {"ok": true}.',
                },
            ],
            "response_format": {"type": "json_object"},
        }

        attempts = 0
        while True:
            attempts += 1
            r = requests.post(
                CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=20
            )
            if r.status_code == 200:
                try:
                    content = r.json()["choices"][0]["message"][
                        "content"
                    ]  # exact match keeps it strict
                    logger.debug(
                        "JSON-probe response content for {}: {}", model_id, content
                    )
                    return json.loads(content) == {"ok": True}
                except Exception:
                    return False

            exc = self.api_error_handler.transform_api_error_to_exception(r, model_id)
            if isinstance(exc, RateLimitError):
                cooldown = max(0, int(exc.cooldown_seconds))
                if cooldown <= INLINE_WAIT_THRESHOLD_SECONDS and attempts <= (
                    1 + MAX_PROBE_INLINE_WAIT_RETRIES
                ):
                    logger.info(
                        "JSON-probe short cooldown {}s for {}, inline waiting then retrying...",
                        cooldown,
                        model_id,
                    )
                    sleep(cooldown)
                    continue
            # not a short cooldown or retries exhausted
            raise exc

    # --- Helper 3: Build LLM Arena × GitHub Models intersection ---
    def _build_llm_arena_scoreboard_intersection(self) -> None:
        """
        Use the official LMArena Elo pickle (elo_results_YYYYMMDD.pkl):
        1) List latest elo_results_*.pkl in the Space
        2) Download + SAFE-unpickle (no Plotly dependency)
        3) Extract Elo dict (prefer 'elo_rating_median', else 'elo_rating_online')
        4) Intersect with our GitHub model IDs
        5) Update our model catalog
        """
        import io
        import pickle
        import requests

        # ---------- helpers ----------
        class _PlotlyFigureStub:
            def __init__(self, *a, **k):
                pass

        class _SafeUnpickler(pickle.Unpickler):
            def find_class(self, module, name):
                # Stub Plotly figure classes so we don't need plotly installed
                if (module, name) in {
                    ("plotly.graph_objs._figure", "Figure"),
                    ("plotly.graph_objs._figurewidget", "FigureWidget"),
                }:
                    return _PlotlyFigureStub
                return super().find_class(module, name)

        def _safe_pickle_load(raw: bytes):
            return _SafeUnpickler(io.BytesIO(raw)).load()

        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

        # ---------- 1) List files ----------
        tree_url = "https://huggingface.co/api/spaces/lmarena-ai/lmarena-leaderboard/tree/main?recursive=1"
        try:
            r = requests.get(tree_url, timeout=15)
            r.raise_for_status()
            listing = r.json()
            pkl_files = [
                entry["path"]
                for entry in listing
                if isinstance(entry, dict)
                and isinstance(entry.get("path"), str)
                and re.fullmatch(r"elo_results_\d{8}\.pkl", entry["path"])
            ]
            if not pkl_files:
                raise RuntimeError("No elo_results_*.pkl found in the Space")

            latest = max(
                pkl_files,
                key=lambda f: int(cast(Match[str], re.search(r"(\d{8})", f)).group(1)),
            )
            pkl_url = f"https://huggingface.co/spaces/lmarena-ai/lmarena-leaderboard/resolve/main/{latest}"
            logger.info("Latest LMArena Elo pickle: {}", pkl_url)
        except Exception as e:
            logger.error("Failed to list Space files for LMArena: {}", e)
            raise RuntimeError("Failed to list Space files for LMArena") from e

        # ---------- 2) Download + SAFE-unpickle ----------
        try:
            resp = requests.get(pkl_url, timeout=15)
            resp.raise_for_status()
            elo_results = _safe_pickle_load(resp.content)
            logger.debug("Top-level Elo result keys: {}", list(elo_results.keys()))
            print(elo_results.keys())
            print(elo_results)
            print("Fin")
        except Exception as e:
            logger.error("Failed to download/unpickle Elo results: {}", e)
            raise RuntimeError("Failed to download/unpickle Elo results") from e

        # ---------- 3) Extract per-task rating tables ----------
        # ModelName = str, Ranking = float
        # ordered_models: list[tuple[ModelName, Ranking]] = elo_results["test"]["overall" or "creative_writing"]...[]

        # ---------- 4) Intersect with our GitHub catalog and update it ----------
        # for model in self.models_catalog:
        #     elo = get_elo_for_model(model, ordered_models)
        #     if elo is not None:
        #         self.models_catalog[model].elo = elo

        return None

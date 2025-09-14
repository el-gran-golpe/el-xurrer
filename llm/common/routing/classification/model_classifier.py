import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Match, cast

import requests
from loguru import logger

from llm.common.api_keys import api_keys
from llm.common.error_handlers.api_error_handler import ApiErrorHandler
from llm.common.routing.classification.constants import UNCENSORED_MODEL_GUESSES
from llm.utils import _clean_chain_of_thought, load_and_prepare_prompts
from main_components.common.types import PromptItem

GITHUB_MODELS_BASE = "https://models.github.ai"
CATALOG_URL = f"{GITHUB_MODELS_BASE}/catalog/models"
CHAT_COMPLETIONS_URL = f"{GITHUB_MODELS_BASE}/inference/chat/completions"
API_VERSION = "2024-08-01-preview"  # TODO: not sure if this is correct or should I use 2022-11-28 version


@dataclass
class LLMModel:
    identifier: str
    supports_json_format: bool
    is_censored: bool
    api_key: str
    elo: float = 1.0  # Hypothetical IQ score for ranking purposes
    is_quota_exhausted: bool = False  # To track rate limit exhaustion
    quota_exhausted_datetime: str = ""  # Timestamp of when quota was exhausted
    cooldown_quota_seconds: float
    max_input_tokens: int = 0
    max_output_tokens: int = 0

    def get_model_response(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> tuple[str, str]:
        logger.info("Using model: {}", self.identifier)

        try:
            assistant_reply = self.get_response_from_github_models(
                conversation=conversation,
                output_as_json=output_as_json,
            )

        except Exception:
            # Here it was use handle_api_error, but we want to handle those errors using the Model router somehow
            raise

        finish_reason = None

        # TODO: Use ModelRouter
        # non_exhausted = [m for m in selected_models if m not in self.exhausted_models]
        # used_model = non_exhausted[0] if non_exhausted else selected_models[0]
        # # TODO: Use ModelRouter
        # if (
        #     not (used_model.startswith("gpt-") or used_model.startswith("o1"))
        #     and finish_reason is None
        # ):
        #     logger.debug(
        #         "Model {} did not return finish reason. Assuming stop", used_model
        #     )
        #     finish_reason = "stop"

        assistant_reply = _clean_chain_of_thought(
            model=self.identifier, assistant_reply=assistant_reply
        )

        # if finish_reason == "stop" and options.validate:
        #     try:
        #         finish_reason, assistant_reply = recalculate_finish_reason(
        #             assistant_reply=assistant_reply,
        #             get_model_response_callable=lambda **k: self._get_model_response(
        #                 **k
        #             ),
        #             preferred_validation_models=self.preferred_validation_models,
        #         )
        #     except Exception:
        #         logger.warning(
        #             "Validation finish_reason failed; proceeding with current reply"
        #         )
        #
        # if finish_reason is None:
        #     raise RuntimeError("Finish reason not found for model response")
        #
        # if any(
        #     cant_assist.lower() in assistant_reply.lower()
        #     for cant_assist in CANNOT_ASSIST_PHRASES
        # ):
        #     if len(models) <= 1:
        #         raise RuntimeError("No models left to assist with prompt.")
        #     logger.warning(
        #         "Assistant cannot assist; trying next model(s): {}", models[1:]
        #     )
        #     models = models[1:]
        #     # continue
        #
        # if finish_reason == "length":
        #     logger.info("Finish reason 'length' encountered; continuing conversation")
        #     conversation = deepcopy(conversation)
        #     conversation.append({"role": "assistant", "content": assistant_reply})
        #     conversation.append(
        #         {"role": "user", "content": "Continue EXACTLY where we left off"}
        #     )
        #     # continue
        # # TODO: Use ModelRouter
        # if finish_reason == "content_filter":
        #     if len(models) <= 1:
        #         raise RuntimeError(
        #             "No more models to retry after content_filter finish reason"
        #         )
        #     models = models[1:]
        #     # continue
        #
        # if finish_reason != "stop":
        #     raise AssertionError(f"Unexpected finish reason: {finish_reason}")

        return assistant_reply, finish_reason

    def get_response_from_github_models(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        payload = {
            "model": self.identifier,
            "messages": conversation,
            **({"response_format": {"type": "json_object"}} if output_as_json else {}),
        }
        try:
            r = requests.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload)
            r.raise_for_status()
        except requests.HTTPError as http_err:
            # INFO: 429 is the status code for rate limit exceeded.
            # This probably means that I have exceeded the UserByModelByQuota and I have to wait
            # around 2.5 hours for this particular model to be reset.
            if r.status_code == 429:
                self.is_quota_exhausted = True
                self.quota_exhausted_datetime = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.gmtime()
                )
                logger.warning(
                    "Model {} quota exhausted at {}.",
                    self.identifier,
                    self.quota_exhausted_datetime,
                )
            else:
                # TODO: what the hell copilot?
                logger.error(
                    "HTTP error occurred for model {}: {} - {}",
                    self.identifier,
                    r.status_code,
                    r.text,
                )
            raise http_err

        data = r.json()

        # TODO: implement the case for ["response_format"] = {"type": "json_object"}
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

        return content


class ModelClassifier:
    """
    This class classifies models based on: IQ, json schema.
    This class should return a ranking of models available for a particular GitHub API key:
    that is, it should return a dict of models, where the keys of this dict is IQ, json schema and
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

    def get_best_model(self, prompt_item: PromptItem) -> LLMModel:
        output_as_json = prompt_item.output_as_json
        is_sensitive_content = prompt_item.is_sensitive_content
        sorted_models = self._get_models_sorted_by_iq()

        for model in sorted_models:
            if model.is_quota_exhausted:
                continue

            # If content is sensitive, skip censored models
            if is_sensitive_content and model.is_censored:
                continue

            # If JSON required, ensure support
            if output_as_json and not model.supports_json_format:
                continue

            return model

        raise RuntimeError("No suitable model found for the given prompt item.")

    def populate_models_catalog(self, models_to_scan: Optional[int]):
        models = self.github_free_catalog
        for model in models[0:models_to_scan]:
            model_id = model.get("id")
            max_input_tokens = model.get("limits", {}).get("max_input_tokens", 0)
            max_output_tokens = model.get("limits", {}).get("max_output_tokens", 0)
            self.models_catalog[model_id] = LLMModel(
                identifier=model_id,
                supports_json_format=self._supports_json_response_format(model_id),
                is_censored=self._is_model_censored(model_id),
                api_key=self.github_api_key,
                is_quota_exhausted=False,
                quota_exhausted_datetime="",
                cooldown_quota_seconds=quota_exhausted_datetime - datetime.now,
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
            )
        # self._build_llm_arena_scoreboard_intersection() # TODO: this method should get the elos for the models in the leaderboard and update the model catalog with the current elo

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

    def _get_models_sorted_by_iq(self) -> list[LLMModel]:
        return sorted(self.models_catalog.values(), key=lambda m: m.elo, reverse=True)

    def _is_model_censored(self, model_id: str) -> bool:
        return not any(
            keyword.lower() in model_id.lower() for keyword in UNCENSORED_MODEL_GUESSES
        )

    def _get_model_elo(self, model_id: str) -> float:
        return self.models_catalog[model_id].elo

    def _mark_model_as_quota_exhausted(self, model_id: str):
        if model_id in self.models_catalog:
            self.models_catalog[model_id].is_quota_exhausted = True
            self.models_catalog[model_id].quota_exhausted_datetime = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.gmtime()
            )
            logger.debug("Model {} marked as quota exhausted.", model_id)
        else:
            logger.error(
                "Model {} not found in catalog to mark as quota exhausted.", model_id
            )

    # --- Helper 1: Does the model support json formatting? ---

    def _supports_json_response_format(self, model_id: str) -> bool:
        """
        Return True if the model accepts response_format={'type': 'json_object'}.
        Result is cached per model id.
        """
        # INFO: API_VERSION might be a mandatory parameter in order to use response_format feature
        headers = {
            "Authorization": f"Bearer {self.github_api_key}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Return a minimal JSON object only."},
                {"role": "user", "content": 'Respond with {"ok": true} only.'},
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            r = requests.post(
                CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
                timeout=10,
            )

            if r.status_code == 200:
                try:
                    content = r.json()["choices"][0]["message"]["content"]
                    ok = json.loads(content) == {
                        "ok": True
                    }  # exact match keeps it strict
                    logger.debug("Model {} supports JSON response format.", model_id)
                    return ok
                except json.JSONDecodeError as e:
                    logger.error(
                        "JSON decode error for model {}: {}. Assuming no JSON support.",
                        model_id,
                        e,
                    )
                    return False
            else:
                error_handler = ApiErrorHandler()
                return error_handler.handle_json_probing_error(r, model_id)

        except requests.exceptions.ReadTimeout as e:
            logger.error(
                "Timeout while checking JSON support for model {}: {}. Assuming no JSON support.",
                model_id,
                e,
            )
            return False

    # --- Helper 2: Build LLM Arena × GitHub Models intersection ---

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


if __name__ == "__main__":
    github_api_keys = api_keys.extract_github_keys()
    prompt_items: list[PromptItem] = load_and_prepare_prompts(
        prompt_json_template_path=Path(
            # r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\fanvue\inputs\laura_vigne.json"
            "/home/moises/repos/gg2/el-xurrer/resources/laura_vigne/fanvue/inputs/laura_vigne.json"
        ),
        previous_storyline="Laura Vigne commited taux fraud and moved to Switzerland.",
    )
    # --- Instantiate classifier and build intersection scoreboard ---
    mc = ModelClassifier(github_api_key=github_api_keys[0])
    mc._build_llm_arena_scoreboard_intersection()

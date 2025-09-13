import re
import sys
import time
from dataclasses import dataclass
from typing import Optional, Match, cast

import requests
from pathlib import Path
from loguru import logger


# --- Ensure project root (containing 'llm') is on sys.path when run as a script ---
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# --- end sys.path setup ---

from llm.utils import load_and_prepare_prompts
from main_components.common.types import PromptItem
from llm.common.api_keys import api_keys

GITHUB_MODELS_BASE = "https://models.github.ai"
CATALOG_URL = f"{GITHUB_MODELS_BASE}/catalog/models"
CHAT_COMPLETIONS_URL = f"{GITHUB_MODELS_BASE}/inference/chat/completions"
API_VERSION = "2024-08-01-preview"  # TODO: not sure if this is correct or should I use 2022-11-28 version

UNCENSORED_MODEL_GUESSES: list[str] = ["deepseek", "grok"]


@dataclass
class LLMModel:
    identifier: str
    supports_json_format: bool
    is_censored: bool
    api_key: str
    elo: float = 1.0  # Hypothetical IQ score for ranking purposes
    is_quota_exhausted: bool = False  # To track rate limit exhaustion
    quota_exhausted_datetime: str = ""  # Timestamp of when quota was exhausted
    max_input_tokens: int = 0
    max_output_tokens: int = 0

    def get_model_response(
        self,
        conversation: list[dict[str, str]],
        output_as_json: bool,
    ):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        print(conversation)

        if output_as_json:
            payload = {
                "model": self.identifier,
                "messages": conversation,
                "response_format": {"type": "json_object"},
                "stream": True,  # INFO: if this is true, it will return chunks
            }
        else:
            payload = {
                "model": self.identifier,
                "messages": conversation,
                "stream": True,
            }

        # payload = {
        #     "model": self.identifier,  # e.g. "openai/gpt-4.1" or "deepseek/deepseek-chat"
        #     "messages": [
        #         {
        #             "role": "system",
        #             "content": "You are an expert storytelling assistant. Reply in JSON with keys: day and outline.",
        #         },
        #         {
        #             "role": "user",
        #             "content": "Your task is to develop a new 7-day storyline... (rest of your prompt)",
        #         },
        #     ],
        #     # Optional: keep only if you truly want JSON mode
        #     "response_format": {"type": "json_object"},
        #     # Optional: set max_tokens, temperature, etc.
        # }
        r = requests.post(
            CHAT_COMPLETIONS_URL, headers=headers, stream=True, json=payload
        )
        r.raise_for_status()
        print(r.json())


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
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
            )
        # self._build_llm_arena_scoreboard_intersection() # TODO: this method should get the elos for the models in the leaderboard and update the model catalog with the current elo

    def _fetch_github_models_catalog(self) -> list[dict]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "Authorization": f"Bearer {self.github_api_key}",
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
            logger.info("Model {} marked as quota exhausted.", model_id)
        else:
            logger.warning(
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
            "Accept": "application/json",
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

        r = requests.post(
            CHAT_COMPLETIONS_URL,
            headers=headers,
            json=payload,
        )

        # TODO: I have the suspicion that this is wrong and I should call the Github api through ChatCompletionsClient

        if r.status_code == 200:
            logger.debug("Model {} supports JSON response format.", model_id)
            logger.debug("Response body: {}", r.text)
            return True

        else:
            logger.debug(
                "Model {} does NOT support JSON response format (status {}).",
                model_id,
                r.status_code,
                r.text,
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

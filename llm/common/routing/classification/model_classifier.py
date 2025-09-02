import csv
import re
import time
from dataclasses import dataclass
from io import StringIO
from typing import Optional

import requests
from pathlib import Path
from loguru import logger

from llm.utils import load_and_prepare_prompts
from main_components.common.types import PromptItem
from llm.common.api_keys import api_keys


@dataclass
class LLMModel:
    identifier: str
    supports_json_format: bool
    is_censored: bool
    iq_score: float  # Hypothetical IQ score for ranking purposes
    is_quota_exhausted: bool = False  # To track rate limit exhaustion
    quota_exhausted_datetime: str = ""  # Timestamp of when quota was exhausted
    max_input_tokens: int = 0
    max_output_tokens: int = 0


UNCENSORED_MODEL_GUESSES: list[str] = ["deepsek", "grok"]


class ModelClassifier:
    """
    This class classifies models based on: IQ, json schema.
    This class should return a ranking of models available for a particular GitHub API key:
    that is, it should return a dict of models, where the keys of this dict is IQ, json schema and
    if it is censored or uncensored.
    """

    GITHUB_MODELS_BASE = "https://models.github.ai"
    CATALOG_URL = f"{GITHUB_MODELS_BASE}/catalog/models"
    CHAT_COMPLETIONS_URL = f"{GITHUB_MODELS_BASE}/inference/chat/completions"
    API_VERSION = "2024-08-01-preview"  # TODO: not sure if this is correct

    # NEW: where we’ll keep the intersection (GitHub model IDs), ordered via LMArena then deduped into a set
    LLM_ARENA_SCOREBOARD: set[str] = set()

    def __init__(
        self,
        github_api_key: str,
    ):
        self.github_api_key: str = github_api_key
        self.github_free_catalog: list[dict] = self._fetch_github_models_catalog()
        # This is the distilled catalog of models we will use for routing
        self.models_catalog: dict[LLMModel] = {}
        self.models_iq_scores: dict[LLMModel.identifier, LLMModel.iq_score] = {}

    # Probably this method and the self.models_catalog will be the main entry points
    # of this class
    def get_best_model(self, prompt_item: PromptItem) -> LLMModel:
        output_json = prompt_item.output_as_json
        censored = prompt_item.is_sensitive_content
        sorted_model = self._get_models_sorted_by_iq()
        for model in sorted_model:
            if (
                model.supports_json_format == output_json
                and model.is_censored == censored
                and not model.is_quota_exhausted
            ):
                return model
        raise RuntimeError("No suitable model found for the given prompt item.")

    def populate_models_catalog(self):
        models = self.github_free_catalog
        for m in models:
            model_id = m.get("id")
            max_input_tokens = m.get("limits", {}).get("max_input_tokens", 0)
            max_output_tokens = m.get("limits", {}).get("max_output_tokens", 0)
            self.models_catalog[model_id] = LLMModel(
                identifier=model_id,
                supports_json_format=self._supports_json_response_format(model_id),
                is_censored=self._is_model_censored(model_id),
                iq_score=self._get_model_iq_score(model_id),
                is_quota_exhausted=False,
                quota_exhausted_datetime="",
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
            )

    # --- Private helpers ---
    def _fetch_github_models_catalog(self) -> list[dict]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.API_VERSION,
            "Authorization": f"Bearer {self.github_api_key}",
        }

        resp = requests.get(self.CATALOG_URL, headers=headers, timeout=30)
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
        return sorted(
            self.models_catalog.values(), key=lambda m: m.iq_score, reverse=True
        )

    def _is_model_censored(self, model_id: str) -> bool:
        return not any(
            keyword.lower() in model_id.lower() for keyword in UNCENSORED_MODEL_GUESSES
        )

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
            "X-GitHub-Api-Version": self.API_VERSION,
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
            self.CHAT_COMPLETIONS_URL,
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

    def _get_model_iq_score(self, model_id: str) -> float:
        pass

    def _build_llm_arena_scoreboard_intersection(self) -> set[str]:
        """
        1) Download latest LMArena leaderboard_table_YYYYMMDD.csv
        2) Parse ELO per model
        3) Match against our GitHub model IDs
        4) Populate self.models_iq_scores with ELO (no normalization)
        5) Return the intersection as a set[str] of matched GitHub model IDs
        """

        # ---- 1) Find & download latest LMArena CSV ----
        tree_url = "https://huggingface.co/api/spaces/lmarena-ai/lmarena-leaderboard/tree/main?recursive=1"
        try:
            response = requests.get(tree_url, timeout=10)
            response.raise_for_status()
            listing = response.json()
            csv_files = [
                entry["path"]
                for entry in listing
                if isinstance(entry, dict)
                and isinstance(entry.get("path"), str)
                and re.fullmatch(r"leaderboard_table_\d{8}\.csv", entry["path"])
            ]
            if not csv_files:
                raise RuntimeError("No leaderboard_table_*.csv found in Space")

            def _date_key(fname: str) -> int:
                return int(re.search(r"leaderboard_table_(\d{8})\.csv", fname).group(1))

            latest_csv = max(csv_files, key=_date_key)
            csv_url = f"https://huggingface.co/spaces/lmarena-ai/lmarena-leaderboard/resolve/main/{latest_csv}"
        except Exception as e:
            logger.error("Failed to list Space files for LMArena: {}", e)
            # fallback snapshot to keep pipeline working
            csv_url = "https://huggingface.co/spaces/lmarena-ai/lmarena-leaderboard/resolve/main/leaderboard_table_20240326.csv"

        try:
            cr = requests.get(csv_url, timeout=timeout)
            cr.raise_for_status()
            csv_text = cr.text
        except Exception as e:
            logger.error("Failed to download LMArena CSV from {}: {}", csv_url, e)
            csv_text = ""

        # TODO: From here onwards, it must be revisited in isolation (this is just pseudo code)
        # ---- 3) Parse CSV → arena_alias_to_elo ----
        arena_alias_to_elo: dict[str, float] = {}
        rows_parsed = 0
        if csv_text:
            reader = csv.DictReader(StringIO(csv_text))
            headers = [h.lower() for h in (reader.fieldnames or [])]
            # likely candidates
            key_col = (
                "key" if "key" in headers else ("model" if "model" in headers else None)
            )
            elo_col = None
            for candidate in ("arena elo rating", "arena elo", "arena score", "elo"):
                if candidate in headers:
                    elo_col = candidate
                    break

            for row in reader:
                if not isinstance(row, dict):
                    continue
                name = (
                    row.get("key") or row.get("Model") or row.get("model") or ""
                ).strip()
                elo_raw = (
                    row.get("Arena Elo rating")
                    or row.get("Arena Elo")
                    or row.get("arena elo rating")
                    or row.get("arena elo")
                    or row.get("Arena Score")
                    or row.get("arena score")
                    or row.get("Elo")
                    or row.get("elo")
                )
                elo_val = _parse_float(elo_raw)
                if not name or elo_val is None:
                    continue
                arena_alias_to_elo[_norm(name)] = float(elo_val)
                rows_parsed += 1

        logger.info("LMArena rows parsed with ELO: {}", rows_parsed)

        # ---- 4) Intersect + populate self.models_iq_scores ----
        self.models_iq_scores = {}
        intersection_ids: list[str] = []
        seen: set[str] = set()

        def _gh_candidates(mid: str) -> list[str]:
            full = _norm(mid)
            tail = _norm(mid.split("/", 1)[-1])
            # try some smart rewrites
            variants = {
                full,
                tail,
                tail.replace("gpt4", "gpt-4"),
                tail.replace("gpt-41", "gpt-4.1"),
                tail.replace("gpt-40", "gpt-4o"),
                tail.replace("claude37", "claude-3.7"),
                tail.replace("claude35", "claude-3.5"),
                tail.replace("llama31", "llama-3.1"),
                tail.replace("llama33", "llama-3.3"),
            }
            return [v for v in variants if v]

        # Prefer using your distilled catalog if present (accurate ID list)
        model_ids = (
            list(self.models_catalog.keys())
            if self.models_catalog
            else [
                (m.get("id") or "").strip()
                for m in gh_text_models
                if (m.get("id") or "").strip()
            ]
        )

        for mid in model_ids:
            elo: Optional[float] = None
            for cand in _gh_candidates(mid):
                if cand in arena_alias_to_elo:
                    elo = arena_alias_to_elo[cand]
                    break
                # also try stripping vendor from candidate against aliases
                if "-" in cand:
                    tail = cand.split("-", 1)[-1]
                    if tail in arena_alias_to_elo:
                        elo = arena_alias_to_elo[tail]
                        break
            if elo is not None:
                # populate IQ map using raw ELO (as requested)
                self.models_iq_scores[mid] = float(elo)
                if mid not in seen:
                    intersection_ids.append(mid)
                    seen.add(mid)
                # also reflect on the LLMModel object if we have it
                if mid in self.models_catalog:
                    self.models_catalog[mid].iq_score = float(elo)

        # ---- 5) Store / return intersection set ----
        ordered_preview = ", ".join(intersection_ids[:10])
        logger.info("Intersection (first 10 in LMArena order): {}", ordered_preview)
        self.LLM_ARENA_SCOREBOARD = set(intersection_ids)
        logger.info("LLM_ARENA_SCOREBOARD size: {}", len(self.LLM_ARENA_SCOREBOARD))
        logger.info("models_iq_scores filled: {} entries", len(self.models_iq_scores))
        return self.LLM_ARENA_SCOREBOARD


if __name__ == "__main__":
    github_api_keys = api_keys.extract_github_keys()
    prompt_items: list[PromptItem] = load_and_prepare_prompts(
        prompt_json_template_path=Path(
            r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\fanvue\inputs\laura_vigne.json"
        ),
        previous_storyline="Laura Vigne commited taux fraud and moved to Switzerland.",
    )
    # --- Instantiate classifier and build intersection scoreboard ---
    mc = ModelClassifier(github_api_key=github_api_keys[0])
    mc._build_llm_arena_scoreboard_intersection()
    # mc.populate_models_catalog()
    # from dataclasses import asdict
    # logger.info("Models catalog size: {}", len(mc.models_catalog))
    # for model_id, model in mc.models_catalog.items():
    #     logger.info("Model id={} -> {}", model_id, asdict(model))

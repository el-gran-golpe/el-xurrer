from dataclasses import dataclass
import json
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
    API_VERSION = "2024-08-01-preview"

    # NEW: where we’ll keep the intersection (GitHub model IDs), ordered via LMArena then deduped into a set
    LLM_ARENA_SCOREBOARD: set[str] = set()

    def __init__(
        self,
        github_api_key: str,
    ):
        self.github_api_key: str = github_api_key
        self.catalog: list[dict] = self._fetch_github_models_catalog()
        self.models_catalog: dict[LLMModel] = {}

    def populate_models_catalog(self):
        models = self._fetch_github_models_catalog()

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

    # def get_model_classification(self) -> dict[str, list[str]]:
    #     """
    #     Classify models based on CI, json schema.
    #     This method should return a ranking of models available for a particular GitHub API key:
    #     that is, it should return a dict of models, where the keys of this dict is CI, json schema and
    #     if it is censored or uncensored.
    #     """
    #     # For simplicity, we will classify based on the model ID string.
    #     # In a real implementation, you would use the catalog data to classify properly.
    #     IQ_scale = set()
    #     json_supported_models = set()
    #     json_unsupported_models = set()
    #     censored_models = set()
    #     uncensored_models = set()
    #
    #     for m in self.catalog:
    #         model_id = m.get("id")
    #         # Let's start checking the constraint of json schema support
    #         if self._supports_json_response_format(model_id):
    #             json_supported_models.add(model_id)
    #         else:
    #             json_unsupported_models.add(model_id)
    #
    #         # Now let's do a CI-based classification
    #         # CI_scale.add(self._build_llm_arena_scoreboard_intersection())
    #
    #     classification = {
    #         "ci": IQ_scale,
    #         "json": json_supported_models,
    #         "censored": censored_models,
    #         "uncensored": uncensored_models,
    #     }
    #
    #     logger.debug("Model classification: {}", classification)
    #     return classification

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

    # --- Helper 1: Does the model support json formatting? ---

    def _supports_json_response_format(self, model_id: str) -> bool:
        """
        Return True if the model accepts response_format={'type': 'json_object'} and
        produces parseable JSON; result is cached per model id.
        """
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

    # def _build_llm_arena_scoreboard_intersection(self) -> set[str]:
    #
    #
    #     # Filter: models that have text output modality (LLM) and are available with rate limits
    #     def _is_text_model(m: dict) -> bool:
    #         if not isinstance(m, dict):
    #             return False
    #         outs: Iterable[str] = m.get("supported_output_modalities") or []
    #         return (not require_text_output) or ("text" in outs)
    #
    #     gh_text_models = [m for m in gh_models if _is_text_model(m)]
    #     logger.info("GitHub catalog text-capable models: {}", len(gh_text_models))
    #
    #     # Build a lookup of canonical GitHub IDs plus normalized aliases
    #     def _norm(s: str) -> str:
    #         s = s.lower()
    #         s = s.strip()
    #         s = s.replace("_", "-").replace("/", "-")
    #         s = re.sub(r"[^a-z0-9.\-]+", "", s)
    #         # coalesce repeated dashes
    #         s = re.sub(r"-{2,}", "-", s)
    #         return s
    #
    #     gh_id_by_alias: dict[str, str] = {}
    #     for m in gh_text_models:
    #         mid = (m.get("id") or "").strip()  # e.g., "openai/gpt-4o-mini"
    #         if not mid:
    #             continue
    #         alias_full = _norm(mid)  # "openai-gpt-4o-mini"
    #         alias_short = _norm(mid.split("/", 1)[-1])  # "gpt-4o-mini"
    #         gh_id_by_alias.setdefault(alias_full, mid)
    #         gh_id_by_alias.setdefault(alias_short, mid)
    #
    #     # -------- 2) Find and download latest LMArena leaderboard_table_YYYYMMDD.csv --------
    #     # Use Hub's tree endpoint to list files in the Space and pick the newest CSV
    #     tree_url = f"https://huggingface.co/api/spaces/{space_owner}/{space_name}/tree/main?recursive=1"
    #     try:
    #         tr = requests.get(tree_url, timeout=timeout)
    #         tr.raise_for_status()
    #         listing = tr.json()
    #         csv_files = [
    #             entry["path"]
    #             for entry in listing
    #             if isinstance(entry, dict)
    #             and isinstance(entry.get("path"), str)
    #             and re.fullmatch(r"leaderboard_table_\d{8}\.csv", entry["path"])
    #         ]
    #         if not csv_files:
    #             raise RuntimeError("No leaderboard_table_*.csv found in Space")
    #
    #         def _date_key(fname: str) -> int:
    #             return int(re.search(r"leaderboard_table_(\d{8})\.csv", fname).group(1))
    #
    #         latest_csv = max(csv_files, key=_date_key)
    #         csv_url = f"https://huggingface.co/spaces/{space_owner}/{space_name}/resolve/main/{latest_csv}"
    #     except Exception as e:
    #         logger.error("Failed to list Space files for LMArena: {}", e)
    #         # Fallback (last-resort): try to fetch a known older CSV so the pipeline still works
    #         csv_url = f"https://huggingface.co/spaces/{space_owner}/{space_name}/resolve/main/leaderboard_table_20240326.csv"
    #
    #     try:
    #         cr = requests.get(csv_url, timeout=timeout)
    #         cr.raise_for_status()
    #         csv_text = cr.text
    #     except Exception as e:
    #         logger.error("Failed to download LMArena CSV from {}: {}", csv_url, e)
    #         csv_text = ""
    #
    #     # -------- 3) Parse CSV and collect model keys in the order they appear --------
    #     arena_keys_ordered: list[str] = []
    #     if csv_text:
    #         reader = csv.DictReader(StringIO(csv_text))
    #         # Prefer "key" column if it exists; otherwise derive from "Model"
    #         has_key = "key" in (reader.fieldnames or [])
    #         for row in reader:
    #             if not isinstance(row, dict):
    #                 continue
    #             raw = (row.get("key") if has_key else row.get("Model")) or ""
    #             if not raw:
    #                 continue
    #             arena_keys_ordered.append(raw)
    #
    #     logger.info("LMArena rows parsed: {}", len(arena_keys_ordered))
    #
    #     # -------- 4) Intersect (normalize both sides); order by LMArena appearance --------
    #     intersection_ids: list[str] = []
    #     seen: set[str] = set()
    #
    #     for raw in arena_keys_ordered:
    #         alias = _norm(raw)
    #         # try exact and a few common transforms
    #         candidates = {
    #             alias,
    #             alias.replace("gpt4", "gpt-4"),  # occasional quirks
    #             alias.replace("gpt-41", "gpt-4.1"),
    #             alias.replace("gpt-40", "gpt-4o"),
    #             alias.replace("claude37", "claude-3.7"),
    #             alias.replace("claude35", "claude-3.5"),
    #             alias.replace("llama31", "llama-3.1"),
    #         }
    #         gh_id: Optional[str] = None
    #         for c in candidates:
    #             if c in gh_id_by_alias:
    #                 gh_id = gh_id_by_alias[c]
    #                 break
    #             # also try stripping vendor if present in alias
    #             if "-" in c:
    #                 tail = c.split("-", 1)[-1]
    #                 if tail in gh_id_by_alias:
    #                     gh_id = gh_id_by_alias[tail]
    #                     break
    #         if gh_id and gh_id not in seen:
    #             intersection_ids.append(gh_id)
    #             seen.add(gh_id)
    #
    #     # -------- 5) Store as a set[str] on the class (and return it) --------
    #     # We keep ordering for logs, but the stored variable is the set as requested.
    #     ordered_preview = ", ".join(intersection_ids[:10])
    #     logger.info("Intersection (first 10 in LMArena order): {}", ordered_preview)
    #     self.LLM_ARENA_SCOREBOARD = set(intersection_ids)
    #     logger.info("LLM_ARENA_SCOREBOARD size: {}", len(self.LLM_ARENA_SCOREBOARD))
    #     return self.LLM_ARENA_SCOREBOARD

    # def _parse_ratelimit_headers(self, headers: Mapping[str, str]) -> dict[str, Any]:
    #     """Return a normalized view of GitHub Models rate-limit headers (both requests and tokens)."""
    #     h = {k.lower(): v for k, v in headers.items()}
    #
    #     def _as_int(name: str) -> int | None:
    #         v = h.get(name)
    #         try:
    #             return int(v) if v is not None and str(v).strip().isdigit() else None
    #         except Exception:
    #             return None
    #
    #     info: dict[str, Any] = {
    #         # requests window
    #         "limit_requests": _as_int("x-ratelimit-limit-requests"),
    #         "remaining_requests": _as_int("x-ratelimit-remaining-requests"),
    #         "reset_requests_epoch": _as_int("x-ratelimit-reset-requests"),
    #         # tokens window
    #         "limit_tokens": _as_int("x-ratelimit-limit-tokens"),
    #         "remaining_tokens": _as_int("x-ratelimit-remaining-tokens"),
    #         "reset_tokens_epoch": _as_int("x-ratelimit-reset-tokens"),
    #         # other helpful bits (may or may not be present)
    #         "model_id": h.get("x-github-model") or h.get("x-model") or None,
    #         "model_tier": h.get("x-github-model-tier") or h.get("x-model-tier") or None,
    #         "request_id": h.get("x-request-id") or None,
    #     }
    #
    #     # Human-friendly reset timestamps if epoch seconds are provided
    #     for k in ("reset_requests_epoch", "reset_tokens_epoch"):
    #         if info[k] is not None:
    #             info[k.replace("_epoch", "_utc")] = time.strftime(
    #                 "%Y-%m-%d %H:%M:%S", time.gmtime(info[k])
    #             )
    #     return info
    #
    # def check_github_models_quota(self, model_id: str | None = None) -> dict[str, Any]:
    #     """
    #     Make a minimal chat completion to retrieve rate-limit headers and per-request usage.
    #     Returns a dict with 'status_code', 'ratelimit', and 'usage' (if available).
    #     Works even if the API returns 429/403—headers are still parsed.
    #     """
    #     # Pick a model if none provided
    #     if not model_id:
    #         if not self._catalog:
    #             self.fetch_github_models_catalog()
    #         for _, models in self._catalog.items():
    #             if models:
    #                 model_id = models[0].get("id")
    #                 break
    #     if not model_id:
    #         logger.error("No model_id available to probe quota.")
    #         return {}
    #
    #     base_headers = {
    #         "Accept": "application/json",
    #         "X-GitHub-Api-Version": API_VERSION,
    #         "Content-Type": "application/json",
    #     }
    #
    #     body = {
    #         "model": model_id,
    #         "messages": [{"role": "user", "content": "ping"}],
    #         "temperature": 0,
    #         "max_tokens": 1,  # cheap probe
    #     }
    #
    #     last_error: Exception | None = None
    #     for token in self.github_api_keys:
    #         try:
    #             resp = requests.post(
    #                 CHAT_COMPLETIONS_URL,
    #                 headers={**base_headers, "Authorization": f"Bearer {token}"},
    #                 json=body,
    #                 timeout=15,
    #             )
    #             # Parse headers regardless of success/failure
    #             rl = self._parse_ratelimit_headers(resp.headers)
    #
    #             usage: dict[str, Any] | None = None
    #             try:
    #                 data = resp.json()
    #                 usage = data.get("usage") if isinstance(data, dict) else None
    #             except Exception:
    #                 usage = None  # non-JSON error bodies are fine
    #
    #             # Log a concise summary
    #             logger.info(
    #                 "Quota probe for model {} -> status={} rem_reqs={}/{} reset={} | rem_tokens={}/{} reset={}",
    #                 model_id,
    #                 resp.status_code,
    #                 rl.get("remaining_requests"),
    #                 rl.get("limit_requests"),
    #                 rl.get("reset_requests_utc"),
    #                 rl.get("remaining_tokens"),
    #                 rl.get("limit_tokens"),
    #                 rl.get("reset_tokens_utc"),
    #             )
    #
    #             return {
    #                 "status_code": resp.status_code,
    #                 "ratelimit": rl,
    #                 "usage": usage,
    #             }
    #         except requests.Timeout as e:
    #             last_error = e
    #             logger.warning("Quota probe timed out for model {}", model_id)
    #             continue
    #         except Exception as e:
    #             last_error = e
    #             logger.warning("Quota probe error: {}", e)
    #             continue
    #
    #     if last_error:
    #         logger.error("All quota probes failed: {}", last_error)
    #     return {}
    def get_best_model(self, prompt_item: PromptItem) -> LLMModel:
        output_json = prompt_item.output_as_json
        censored = prompt_item.is_sensitive_content
        sorted_model = self._get_model_ordered_by_iq()
        for model in sorted_model:
            if (
                model.supports_json_format == output_json
                and model.is_censored == censored
                and not model.is_quota_exhausted
            ):
                return model
        raise RuntimeError("No suitable model found for the given prompt item.")

    def _get_model_ordered_by_iq(self):
        # Sort models by IQ score in descending order
        sorted_models = sorted(
            self.models_catalog.values(), key=lambda m: m.iq_score, reverse=True
        )
        return sorted_models

    def _get_model_iq_score(self, model_id: str) -> int:
        pass

    def _is_model_censored(self, model_id: str) -> bool:
        pass

    def mark_model_as_quota_exhausted(self, model_id: str):
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
    classification = mc.get_model_classification()

    try:
        scoreboard_set = mc.build_llm_arena_scoreboard_intersection()
        # Store already lives in mc.LLM_ARENA_SCOREBOARD; `scoreboard_set` returned for convenience.
        logger.success("LLM_ARENA_SCOREBOARD size: {}", len(scoreboard_set))

        # Debug preview (first 20, sorted for readability only here)
        preview = sorted(list(scoreboard_set))[:20]
        logger.info("Scoreboard preview (first 20 sorted for display): {}", preview)

        # Persist a debug artifact so we can inspect easily
        out_path = Path("llm_arena_scoreboard.json")
        try:
            out_path.write_text(
                json.dumps(sorted(list(scoreboard_set)), indent=2), encoding="utf-8"
            )
            logger.info("Wrote debug scoreboard to {}", out_path.resolve())
        except Exception as e:
            logger.warning("Could not write {}: {}", out_path, e)

    except Exception as e:
        logger.exception("Failed building LMArena × GitHub Models intersection: {}", e)

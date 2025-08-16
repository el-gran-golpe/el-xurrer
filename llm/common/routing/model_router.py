import json
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
        self._catalog: dict[str, list[dict]] = {}
        self._json_support_cache: dict[str, bool] = {}

    def get_best_available_model(self, prompt_item: PromptItem) -> str | None:
        catalog = self.fetch_github_models_catalog()
        json_capabilities = self.classify_according_to_json_schema(catalog)

        # Prefer models that support JSON
        for alias, models in catalog.items():
            for m in models:
                mid = m.get("id")
                if not mid:
                    continue
                if json_capabilities.get(mid):
                    logger.info("Selected JSON-capable model {} (alias {})", mid, alias)
                    return mid

        # Fallback: first model in catalog
        for alias, models in catalog.items():
            if models:
                mid = models[0].get("id")
                logger.warning("No JSON-capable model found; falling back to {}", mid)
                return mid
        logger.error("No models found in catalog.")
        return None

    def fetch_github_models_catalog(self) -> dict[str, list[dict]]:
        catalogs: dict[str, list[dict]] = {}
        token_alias = {tok: f"gh_{i + 1}" for i, tok in enumerate(self.github_api_keys)}
        base_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        for token in self.github_api_keys:
            alias = token_alias[token]
            try:
                resp = requests.get(
                    CATALOG_URL,
                    headers={**base_headers, "Authorization": f"Bearer {token}"},
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                models = data if isinstance(data, list) else []
                catalogs[alias] = models
                logger.info("Catalog for {}: {} models", alias, len(models))
                for m in models:
                    mid = m.get("id", "<no-id>")
                    pub = m.get("publisher") or m.get("registry") or "<unknown>"
                    tier = m.get("rate_limit_tier") or "n/a"
                    in_mods = ",".join(m.get("supported_input_modalities", [])) or "-"
                    out_mods = ",".join(m.get("supported_output_modalities", [])) or "-"
                    logger.info(
                        "  • {} | publisher={} | tier={} | in=[{}] out=[{}]",
                        mid,
                        pub,
                        tier,
                        in_mods,
                        out_mods,
                    )
            except Exception as e:
                logger.error("Failed fetching catalog for {}: {}", alias, e)
                catalogs[alias] = []
        self._catalog = catalogs
        return catalogs

    def classify_according_to_json_schema(
        self, catalog: dict[str, list[dict]]
    ) -> dict[str, bool]:
        """
        Probe every model once to detect support for response_format=json_object.
        Returns mapping: model_id -> bool.
        Uses cache to avoid re-probing already known models.
        """
        schema = {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "summary": {"type": "string"},
            },
            "required": ["ok", "summary"],
        }
        user_prompt = (
            "Return ONLY a JSON object (no commentary) conforming to this schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        base_headers = {
            "Accept": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
            "Content-Type": "application/json",
        }

        # Collect unique model ids
        model_ids: list[str] = []
        for models in catalog.values():
            for m in models:
                mid = m.get("id")
                if mid and mid not in self._json_support_cache and mid not in model_ids:
                    model_ids.append(mid)

        if not model_ids:
            return self._json_support_cache

        logger.info("Probing JSON support for {} model(s)", len(model_ids))

        for mid in model_ids:
            supported = False
            for token in self.github_api_keys:
                body = {
                    "model": mid,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You output only valid JSON object. No extra text.",
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 128,
                    "response_format": {"type": "json_object"},
                }
                try:
                    resp = requests.post(
                        CHAT_COMPLETIONS_URL,
                        headers={**base_headers, "Authorization": f"Bearer {token}"},
                        json=body,
                        timeout=25,
                    )
                except requests.Timeout:
                    logger.debug("Timeout probing {}", mid)
                    continue
                except Exception as e:
                    logger.debug("Request error probing {}: {}", mid, e)
                    continue

                if resp.status_code != 200:
                    # Unsupported or rejected; try next key
                    logger.debug(
                        "Probe {} status {} body_head={}",
                        mid,
                        resp.status_code,
                        resp.text[:160],
                    )
                    continue

                try:
                    data = resp.json()
                except Exception:
                    logger.debug("Non-JSON HTTP response for {}", mid)
                    continue

                choices = data.get("choices") or []
                if not choices:
                    logger.debug("Empty choices for {}", mid)
                    continue

                content = choices[0].get("message", {}).get("content", "").strip()
                if content.startswith("```"):
                    lines = content.splitlines()
                    if len(lines) >= 2 and lines[-1].startswith("```"):
                        content = "\n".join(lines[1:-1]).strip()
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    logger.debug(
                        "Model {} returned non-parseable content head={}",
                        mid,
                        content[:120],
                    )
                    continue

                required = schema["required"]
                if not all(k in parsed for k in required):
                    logger.debug(
                        "Model {} JSON missing required keys {}", mid, required
                    )
                    continue

                supported = True
                logger.info("Model {} supports JSON mode", mid)
                break  # stop trying more tokens for this model

            if not supported:
                logger.info("Model {} does NOT support JSON mode", mid)
            self._json_support_cache[mid] = supported
            time.sleep(0.3)  # gentle pacing

        return self._json_support_cache

    def _parse_ratelimit_headers(self, headers: Mapping[str, str]) -> dict[str, Any]:
        """Return a normalized view of GitHub Models rate-limit headers (both requests and tokens)."""
        h = {k.lower(): v for k, v in headers.items()}

        def _as_int(name: str) -> int | None:
            v = h.get(name)
            try:
                return int(v) if v is not None and str(v).strip().isdigit() else None
            except Exception:
                return None

        info: dict[str, Any] = {
            # requests window
            "limit_requests": _as_int("x-ratelimit-limit-requests"),
            "remaining_requests": _as_int("x-ratelimit-remaining-requests"),
            "reset_requests_epoch": _as_int("x-ratelimit-reset-requests"),
            # tokens window
            "limit_tokens": _as_int("x-ratelimit-limit-tokens"),
            "remaining_tokens": _as_int("x-ratelimit-remaining-tokens"),
            "reset_tokens_epoch": _as_int("x-ratelimit-reset-tokens"),
            # other helpful bits (may or may not be present)
            "model_id": h.get("x-github-model") or h.get("x-model") or None,
            "model_tier": h.get("x-github-model-tier") or h.get("x-model-tier") or None,
            "request_id": h.get("x-request-id") or None,
        }

        # Human-friendly reset timestamps if epoch seconds are provided
        for k in ("reset_requests_epoch", "reset_tokens_epoch"):
            if info[k] is not None:
                info[k.replace("_epoch", "_utc")] = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.gmtime(info[k])
                )
        return info

    def check_github_models_quota(self, model_id: str | None = None) -> dict[str, Any]:
        """
        Make a minimal chat completion to retrieve rate-limit headers and per-request usage.
        Returns a dict with 'status_code', 'ratelimit', and 'usage' (if available).
        Works even if the API returns 429/403—headers are still parsed.
        """
        # Pick a model if none provided
        if not model_id:
            if not self._catalog:
                self.fetch_github_models_catalog()
            for _, models in self._catalog.items():
                if models:
                    model_id = models[0].get("id")
                    break
        if not model_id:
            logger.error("No model_id available to probe quota.")
            return {}

        base_headers = {
            "Accept": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
            "Content-Type": "application/json",
        }

        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 1,  # cheap probe
        }

        last_error: Exception | None = None
        for token in self.github_api_keys:
            try:
                resp = requests.post(
                    CHAT_COMPLETIONS_URL,
                    headers={**base_headers, "Authorization": f"Bearer {token}"},
                    json=body,
                    timeout=15,
                )
                # Parse headers regardless of success/failure
                rl = self._parse_ratelimit_headers(resp.headers)

                usage: dict[str, Any] | None = None
                try:
                    data = resp.json()
                    usage = data.get("usage") if isinstance(data, dict) else None
                except Exception:
                    usage = None  # non-JSON error bodies are fine

                # Log a concise summary
                logger.info(
                    "Quota probe for model {} -> status={} rem_reqs={}/{} reset={} | rem_tokens={}/{} reset={}",
                    model_id,
                    resp.status_code,
                    rl.get("remaining_requests"),
                    rl.get("limit_requests"),
                    rl.get("reset_requests_utc"),
                    rl.get("remaining_tokens"),
                    rl.get("limit_tokens"),
                    rl.get("reset_tokens_utc"),
                )

                return {
                    "status_code": resp.status_code,
                    "ratelimit": rl,
                    "usage": usage,
                }
            except requests.Timeout as e:
                last_error = e
                logger.warning("Quota probe timed out for model {}", model_id)
                continue
            except Exception as e:
                last_error = e
                logger.warning("Quota probe error: {}", e)
                continue

        if last_error:
            logger.error("All quota probes failed: {}", last_error)
        return {}


if __name__ == "__main__":
    github_api_keys = api_keys.extract_github_keys()
    openai_api_keys = api_keys.extract_openai_keys()
    prompt_items: list[PromptItem] = load_and_prepare_prompts(
        prompt_json_template_path=Path(
            r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\fanvue\inputs\laura_vigne.json"
        ),
        previous_storyline="Laura Vigne commited taux fraud and moved to Switzerland.",
    )
    router = ModelRouter(github_api_keys, openai_api_keys)
    catalog = router.fetch_github_models_catalog()
    best = router.get_best_available_model(prompt_items[0])
    logger.success("BEST MODEL: {}", best)

    quota = router.check_github_models_quota(best)
    logger.info("Quota snapshot: {}", quota)

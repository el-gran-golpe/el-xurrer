import requests
from loguru import logger

from llm.utils import load_and_prepare_prompts
from main_components.common.types import Platform
from main_components.common.types import PromptItem
from pathlib import Path

GITHUB_MODELS_BASE = "https://models.github.ai"
CATALOG_URL = f"{GITHUB_MODELS_BASE}/catalog/models"
CHAT_COMPLETIONS_URL = f"{GITHUB_MODELS_BASE}/inference/chat/completions"
API_VERSION = "2022-11-28"  # per GitHub REST docs

from llm.common.api_keys import api_keys


class ModelRouter:
    """Fetches GitHub Models catalog and picks a model that satisfies requirements.

    This router:
      * Fetches the catalog per key (free tier varies by account/org).
      * Filters by modalities and optional allow/block lists.
      * Accounts for JSON/JSON-schema needs by probing a model once and caching the result.
      * Tracks cooldowns by (token, model) and rotates among 3+ keys.
      * Exposes a single `pick()` returning a SelectedModel (with key alias).
    """

    def __init__(
        self,
        github_api_keys: list[str],
        openai_api_keys: list[str],
        platform_name: Platform,
    ):
        self.github_api_keys = github_api_keys
        self.openai_api_keys = openai_api_keys
        self.prompt_items: list[PromptItem]

        self.remaining_quota_usage: dict[str, int] = {}

    def fetch_github_models_catalog(self) -> dict[str, list[dict]]:
        catalogs: dict[str, list[dict]] = {}

        # Build stable aliases so we don't print raw tokens
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

        return catalogs


if __name__ == "__main__":
    github_api_keys = api_keys.extract_github_keys()
    openai_api_keys = api_keys.extract_openai_keys()

    prompt_items: list[PromptItem] = load_and_prepare_prompts(
        prompt_json_template_path=Path(
            r"C:\Users\Usuario\source\repos\shared-with-haru\el-xurrer\resources\laura_vigne\fanvue\inputs\laura_vigne.json"
        ),
        previous_storyline="Laura Vigne commited taux fraud and moved to Switzerland.",
    )

    model_router = ModelRouter(
        github_api_keys=github_api_keys,
        openai_api_keys=openai_api_keys,
        prompt_items=prompt_items,
    )
    catalog = model_router.fetch_github_models_catalog()

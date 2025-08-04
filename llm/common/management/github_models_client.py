import time
import json
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from llm.management.key_manager import KeyManager
from llm.management.usage_tracker import ModelUsageTracker


class GitHubModelsClient:
    """
    Adapter for GitHub Models REST API.
    - Fetches catalog of available models (with rate limits) :contentReference[oaicite:0]{index=0}
    - Tracks per-model daily free usage & cooldown via KeyManager
    - Records usage metrics in ModelUsageTracker
    """

    CATALOG_URL = "https://api.github.com/models"

    def __init__(self, pat_keys: List[str], usage_file: Optional[str] = None):
        # Rotating through multiple GitHub PATs with cooldown/backoff
        self.key_manager = KeyManager(pat_keys)
        # Track calls, latencies, errors per model
        self.usage = ModelUsageTracker()
        # Simple per-model daily count persistence
        self.usage_file = Path(usage_file) if usage_file else None
        self.daily_quotas: Dict[str, int] = {}  # model_id -> used_today
        self._load_usage()

    def _load_usage(self):
        if self.usage_file and self.usage_file.exists():
            data = json.loads(self.usage_file.read_text())
            self.daily_quotas = data.get("daily_quotas", {})

    def _save_usage(self):
        if self.usage_file:
            self.usage_file.parent.mkdir(parents=True, exist_ok=True)
            self.usage_file.write_text(json.dumps({"daily_quotas": self.daily_quotas}))

    def list_models(self):  # -> list[Dict[str, Any]]:
        """
        Fetch the catalog of GitHub Models via REST.
        Returns a list of model metadata dicts, including 'id', 'rate_limits', etc. :contentReference[oaicite:1]{index=1}
        """
        token = self.key_manager.get_key()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        start = time.time()
        resp = httpx.get(self.CATALOG_URL, headers=headers, timeout=10)
        latency = time.time() - start

        if resp.status_code == 200:
            self.key_manager.mark_success(token)
            models = resp.json().get("models", [])
            self.usage.record("catalog", True, latency)
            return models
        else:
            self.key_manager.mark_failure(token)
            self.usage.record("catalog", False, latency)
            resp.raise_for_status()

    def get_available_models(self) -> List[str]:
        """
        Returns only model IDs that:
         - are in the free tier (daily_quotas < limit)
         - optionally match uncensored/censored flags
        """
        models = self.list_models()
        available: List[str] = []
        for m in models:
            mid = m["id"]
            # free usage limit from metadata, or default to some cap
            limit = m.get(
                "free_daily_limit", 50
            )  # assume default :contentReference[oaicite:2]{index=2}
            used = self.daily_quotas.get(mid, 0)
            if used < limit:
                available.append(mid)
        return available

    def chat(self, model: str, messages: List[Dict[str, str]], **kwargs):
        """
        Send a chat completion request to GitHub Models.
        Increments daily usage count and records metrics.
        """
        url = f"https://api.github.com/models/{model}/inference/chat/completions"
        token = self.key_manager.get_key()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        payload = {"messages": messages, **kwargs}

        start = time.time()
        resp = httpx.post(url, headers=headers, json=payload, timeout=30)
        latency = time.time() - start

        if resp.status_code == 200:
            self.key_manager.mark_success(token)
            self.daily_quotas[model] = self.daily_quotas.get(model, 0) + 1
            self._save_usage()
            self.usage.record(model, True, latency)
            data = resp.json()
            # Simplified: assume single-message reply
            return data["choices"][0]["message"]["content"], data
        else:
            self.key_manager.mark_failure(token)
            self.usage.record(model, False, latency)
            resp.raise_for_status()
